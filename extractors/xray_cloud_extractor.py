"""Extractor for Xray Cloud using GraphQL API."""

from typing import Dict, Any, List
from pathlib import Path
from tqdm import tqdm

from extractors.base_extractor import BaseExtractor
from repositories.xray_cloud_repository import XrayCloudRepository
from utils.graphql_client import GraphQLClient
from utils.logger import get_logger

logger = get_logger(__name__)


class XrayCloudExtractor(BaseExtractor):
    """
    Extractor for Xray Cloud that pulls data via GraphQL API.
    
    Extracts:
    - Projects
    - Folders
    - Test Cases
    - Test Executions
    - Test Runs (nested in executions)
    - Attachments
    """
    
    def __init__(self, cache_manager, graphql_client: GraphQLClient):
        """
        Initialize Xray Cloud extractor.
        
        Args:
            cache_manager: CacheManager instance
            graphql_client: Configured GraphQLClient instance
        """
        super().__init__(cache_manager)
        self.client = graphql_client
        self.repository = XrayCloudRepository(graphql_client)
        self.errors: List[str] = []
    
    def extract(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract all data from Xray Cloud.
        
        Args:
            config: Configuration dictionary with:
                - projects: List of project keys to extract
                - (other config fields are used from client initialization)
        
        Returns:
            Dictionary with extraction statistics
        """
        self.logger.info("Starting Xray Cloud extraction...")
        
        project_keys = config.get("projects", [])
        if not project_keys:
            raise ValueError("No projects specified in config")
        
        stats = {
            "projects": 0,
            "folders": 0,
            "test_cases": 0,
            "test_executions": 0,
            "test_runs": 0,
            "attachments": 0,
            "errors": 0
        }
        
        all_projects = []
        all_folders = []
        all_test_cases = []
        all_test_executions = []
        all_attachments = []
        attachment_ids = set()
        
        # Extract projects
        self.logger.info("=" * 60)
        self.logger.info("PHASE 1: Extracting Projects")
        self.logger.info("=" * 60)
        
        try:
            projects = self.repository.get_projects(project_keys)
            all_projects.extend(projects)
            stats["projects"] = len(projects)
            self.cache_manager.save_raw_data("projects", projects)
            if len(projects) == 0:
                self.logger.warning("No projects fetched via REST API. Will try to derive project info from test cases.")
        except Exception as e:
            error_msg = f"Failed to extract projects: {e}"
            self.logger.error(error_msg)
            self.logger.warning("Continuing without project data. Will derive project info from test cases.")
            self.errors.append(error_msg)
            stats["errors"] += 1
        
        # Extract folders, tests, and executions for each project
        for project_key in tqdm(project_keys, desc="Processing projects"):
            try:
                # Get project ID from projects data
                project_id = None
                for proj in all_projects:
                    if proj.get("key") == project_key:
                        project_id = proj.get("id")
                        break
                
                if not project_id:
                    self.logger.warning(f"Could not find project ID for {project_key}, skipping folders")
                else:
                    # Extract folders
                    self.logger.info(f"Extracting folders for project {project_key}...")
                    try:
                        folders = self.repository.get_folders(project_id)
                        all_folders.extend(folders)
                        stats["folders"] += len(folders)
                    except Exception as e:
                        error_msg = f"Failed to extract folders for {project_key}: {e}"
                        self.logger.error(error_msg)
                        self.errors.append(error_msg)
                        stats["errors"] += 1
                
                # Extract test cases
                self.logger.info(f"Extracting test cases for project {project_key}...")
                try:
                    tests = self.repository.get_tests(project_key)
                    all_test_cases.extend(tests)
                    stats["test_cases"] += len(tests)
                    
                    # Collect attachment IDs from tests
                    for test in tests:
                        jira_data = test.get("jira", {})
                        attachments = jira_data.get("attachment", [])
                        if attachments:
                            attachment_ids.update(attachments)
                except Exception as e:
                    error_msg = f"Failed to extract tests for {project_key}: {e}"
                    self.logger.error(error_msg)
                    self.errors.append(error_msg)
                    stats["errors"] += 1
                
                # Extract test executions
                self.logger.info(f"Extracting test executions for project {project_key}...")
                try:
                    executions = self.repository.get_test_executions(project_key)
                    all_test_executions.extend(executions)
                    stats["test_executions"] += len(executions)
                    
                    # Count test runs and collect attachment IDs
                    for execution in executions:
                        test_runs = execution.get("testRuns", {}).get("results", [])
                        stats["test_runs"] += len(test_runs)
                        
                        # Collect attachments from execution Jira data
                        jira_data = execution.get("jira", {})
                        attachments = jira_data.get("attachment", [])
                        if attachments:
                            attachment_ids.update(attachments)
                except Exception as e:
                    error_msg = f"Failed to extract test executions for {project_key}: {e}"
                    self.logger.error(error_msg)
                    self.errors.append(error_msg)
                    stats["errors"] += 1
                    
            except Exception as e:
                error_msg = f"Error processing project {project_key}: {e}"
                self.logger.error(error_msg)
                self.errors.append(error_msg)
                stats["errors"] += 1
        
        # Derive project info from test cases if projects weren't fetched
        if len(all_projects) == 0 and len(all_test_cases) > 0:
            self.logger.info("Deriving project information from test cases...")
            project_ids_seen = set()
            for test in all_test_cases:
                project_id = test.get("projectId")
                if project_id and project_id not in project_ids_seen:
                    project_ids_seen.add(project_id)
                    # Create a minimal project entry
                    all_projects.append({
                        "id": project_id,
                        "key": project_keys[0] if project_keys else "UNKNOWN",
                        "name": f"Project {project_id}",
                        "derived_from_tests": True
                    })
            if all_projects:
                stats["projects"] = len(all_projects)
                self.cache_manager.save_raw_data("projects", all_projects)
                self.logger.info(f"Derived {len(all_projects)} project(s) from test cases")
        
        # Derive folders from test cases if folders weren't fetched
        if len(all_folders) == 0 and len(all_test_cases) > 0:
            self.logger.info("Deriving folder information from test cases...")
            folders_seen = {}
            for test in all_test_cases:
                folder_info = test.get("folder")
                if folder_info and isinstance(folder_info, dict):
                    folder_path = folder_info.get("path")
                    project_id = test.get("projectId")
                    if folder_path and project_id:
                        # Create unique key for folder
                        folder_key = f"{project_id}:{folder_path}"
                        if folder_key not in folders_seen:
                            folders_seen[folder_key] = {
                                "projectId": project_id,
                                "path": folder_path,
                                "name": folder_path.split("/")[-1] if folder_path != "/" else "Root",
                                "testsCount": 0,
                                "derived_from_tests": True
                            }
                        # Count tests in this folder
                        folders_seen[folder_key]["testsCount"] += 1
            
            if folders_seen:
                all_folders.extend(list(folders_seen.values()))
                stats["folders"] = len(all_folders)
                self.logger.info(f"Derived {len(all_folders)} folder(s) from test cases")
        
        # Save extracted data
        self.logger.info("=" * 60)
        self.logger.info("Saving extracted data to cache...")
        self.logger.info("=" * 60)
        
        if all_folders:
            self.cache_manager.save_raw_data("folders", all_folders)
        
        if all_test_cases:
            self.cache_manager.save_raw_data("test_cases", all_test_cases)
        
        if all_test_executions:
            self.cache_manager.save_raw_data("test_executions", all_test_executions)
        
        # Extract attachments
        if attachment_ids:
            self.logger.info(f"Extracting {len(attachment_ids)} attachments...")
            try:
                attachments = self.repository.get_attachments(list(attachment_ids))
                all_attachments.extend(attachments)
                stats["attachments"] = len(attachments)
                self.cache_manager.save_raw_data("attachments", attachments)
            except Exception as e:
                error_msg = f"Failed to extract attachments: {e}"
                self.logger.error(error_msg)
                self.errors.append(error_msg)
                stats["errors"] += 1
        
        # Save errors to log file
        if self.errors:
            error_log_path = self.cache_manager.cache_dir / "extraction_errors.log"
            with open(error_log_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(self.errors))
            self.logger.warning(f"Saved {len(self.errors)} errors to {error_log_path}")
        
        # Save metadata
        self.save_extraction_metadata(stats)
        
        # Print summary
        self.logger.info("=" * 60)
        self.logger.info("EXTRACTION COMPLETE")
        self.logger.info("=" * 60)
        self.logger.info(f"Projects: {stats['projects']}")
        self.logger.info(f"Folders: {stats['folders']}")
        self.logger.info(f"Test Cases: {stats['test_cases']}")
        self.logger.info(f"Test Executions: {stats['test_executions']}")
        self.logger.info(f"Test Runs: {stats['test_runs']}")
        self.logger.info(f"Attachments: {stats['attachments']}")
        self.logger.info(f"Errors: {stats['errors']}")
        self.logger.info(f"Cache directory: {self.cache_manager.cache_dir}")
        
        return stats
