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
        
        # Projects and folders will be derived from test cases (Xray GraphQL only)
        # No need to call Jira REST API for projects - we'll extract everything from Xray GraphQL
        
        # Extract tests and executions for each project (using Xray GraphQL only)
        self.logger.info("=" * 60)
        self.logger.info("PHASE 0: Extracting Test Cases and Executions (Xray GraphQL)")
        self.logger.info("=" * 60)
        
        for project_key in tqdm(project_keys, desc="Processing projects"):
            try:
                # Extract test cases
                self.logger.info(f"Extracting test cases for project {project_key}...")
                try:
                    tests = self.repository.get_tests(project_key)
                    all_test_cases.extend(tests)
                    stats["test_cases"] += len(tests)
                    
                    # Collect attachment IDs from tests
                    attachment_count = 0
                    for test in tests:
                        jira_data = test.get("jira", {})
                        attachments = jira_data.get("attachment", [])
                        if attachments:
                            # Handle both string IDs and attachment objects
                            for attachment in attachments:
                                if isinstance(attachment, str):
                                    attachment_ids.add(attachment)
                                    attachment_count += 1
                                elif isinstance(attachment, dict):
                                    # Extract ID from attachment object
                                    att_id = attachment.get("id") or attachment.get("attachmentId")
                                    if att_id:
                                        attachment_ids.add(str(att_id))
                                        attachment_count += 1
                                else:
                                    # Try to convert to string
                                    attachment_ids.add(str(attachment))
                                    attachment_count += 1
                    if attachment_count > 0:
                        self.logger.info(f"Collected {attachment_count} attachment ID(s) from test cases")
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
                            # Handle both string IDs and attachment objects
                            for attachment in attachments:
                                if isinstance(attachment, str):
                                    attachment_ids.add(attachment)
                                elif isinstance(attachment, dict):
                                    # Extract ID from attachment object
                                    att_id = attachment.get("id") or attachment.get("attachmentId")
                                    if att_id:
                                        attachment_ids.add(str(att_id))
                                else:
                                    # Try to convert to string
                                    attachment_ids.add(str(attachment))
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
        
        # Derive project info from test cases (always derive from Xray GraphQL data)
        self.logger.info("=" * 60)
        self.logger.info("PHASE 1: Deriving Projects from Test Cases")
        self.logger.info("=" * 60)
        
        if len(all_test_cases) > 0:
            self.logger.info("Deriving project information from test cases...")
            project_ids_seen = set()
            # Map project IDs to their keys from config
            project_id_to_key = {}
            for test in all_test_cases:
                project_id = test.get("projectId")
                if project_id and project_id not in project_ids_seen:
                    project_ids_seen.add(project_id)
                    # Find matching project key from config
                    # Try to match by checking if test's projectId matches any known project
                    # For now, use the first project key from config (we can improve this later)
                    matching_key = project_keys[0] if project_keys else "UNKNOWN"
                    project_id_to_key[project_id] = matching_key
                    # Create a project entry
                    all_projects.append({
                        "id": project_id,
                        "key": matching_key,
                        "name": f"Project {matching_key}",
                        "derived_from_tests": True
                    })
            if all_projects:
                stats["projects"] = len(all_projects)
                self.cache_manager.save_raw_data("projects", all_projects)
                self.logger.info(f"Derived {len(all_projects)} project(s) from test cases")
        else:
            self.logger.warning("No test cases found - cannot derive project information")
        
        # Derive folders from test cases (always derive from Xray GraphQL data)
        self.logger.info("=" * 60)
        self.logger.info("PHASE 2: Deriving Folders from Test Cases")
        self.logger.info("=" * 60)
        
        if len(all_test_cases) > 0:
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
        
        # Extract attachments from test cases and executions (already included in the data)
        self.logger.info(f"Total attachment IDs collected: {len(attachment_ids)}")
        if attachment_ids:
            self.logger.info(f"Extracting attachment metadata for {len(attachment_ids)} attachments...")
            self.logger.debug(f"Attachment IDs: {list(attachment_ids)[:10]}...")  # Show first 10 IDs
            
            # Extract attachment objects directly from test cases and executions
            # (They're already in the data, no need to fetch via REST API)
            attachments_seen = {}
            
            # Collect from test cases
            for test in all_test_cases:
                jira_data = test.get("jira", {})
                attachments = jira_data.get("attachment", [])
                for attachment in attachments:
                    if isinstance(attachment, dict):
                        att_id = attachment.get("id") or attachment.get("attachmentId")
                        if att_id and str(att_id) not in attachments_seen:
                            attachments_seen[str(att_id)] = attachment
            
            # Collect from test executions
            for execution in all_test_executions:
                jira_data = execution.get("jira", {})
                attachments = jira_data.get("attachment", [])
                for attachment in attachments:
                    if isinstance(attachment, dict):
                        att_id = attachment.get("id") or attachment.get("attachmentId")
                        if att_id and str(att_id) not in attachments_seen:
                            attachments_seen[str(att_id)] = attachment
            
            if attachments_seen:
                all_attachments.extend(list(attachments_seen.values()))
                stats["attachments"] = len(all_attachments)
                
                # Download attachment files (requires Basic Auth - email + API token)
                # OAuth 2.0 doesn't work for Jira Cloud REST API (requires user interaction)
                has_jira_creds = bool(
                    self.client.jira_email and self.client.jira_api_token
                )
                if has_jira_creds:
                    self.logger.info("=" * 60)
                    self.logger.info("PHASE 3: Downloading Attachment Files")
                    self.logger.info("=" * 60)
                    
                    # Test Jira authentication first
                    self.logger.info("Testing Jira authentication credentials...")
                    auth_works = self.client.test_jira_auth()
                    if not auth_works:
                        self.logger.error("❌ Jira authentication test failed!")
                        self.logger.error("   Please verify your Jira credentials in config.json")
                        self.logger.error("   Skipping attachment downloads due to authentication failure")
                        self.errors.append("Jira authentication test failed - cannot download attachments")
                    else:
                        self._download_attachments(all_attachments)
                else:
                    self.logger.warning("=" * 60)
                    self.logger.warning("PHASE 3: Skipping Attachment File Downloads")
                    self.logger.warning("=" * 60)
                    self.logger.warning("Jira credentials not provided.")
                    self.logger.warning("Attachment metadata will be saved, but files will not be downloaded.")
                    self.logger.warning("To download attachments, add either:")
                    self.logger.warning("  - 'jira_email' and 'jira_api_token' for Basic Auth, OR")
                    self.logger.warning("  - 'jira_oauth_client_id' and 'jira_oauth_client_secret' for OAuth 2.0")
                    self.logger.warning("Attachments can be downloaded later during Transform/Load phase if needed.")
                
                self.cache_manager.save_raw_data("attachments", all_attachments)
                self.logger.info(f"Successfully extracted {len(all_attachments)} attachment(s) from test data")
            else:
                self.logger.warning(f"Found {len(attachment_ids)} attachment IDs but couldn't extract attachment objects")
        else:
            self.logger.info("No attachments found in test cases or executions")
        
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
    
    def _download_attachments(self, attachments: List[Dict[str, Any]]) -> None:
        """
        Download attachment files and store them locally.
        
        Args:
            attachments: List of attachment metadata dictionaries
        """
        if not attachments:
            return
        
        self.logger.info(f"Downloading {len(attachments)} attachment file(s)...")
        
        downloaded_count = 0
        failed_count = 0
        
        for attachment in tqdm(attachments, desc="Downloading attachments"):
            try:
                attachment_id = str(attachment.get("id") or attachment.get("attachmentId", ""))
                content_url = attachment.get("content")
                filename = attachment.get("filename", f"attachment_{attachment_id}")
                
                if not content_url:
                    self.logger.warning(f"Attachment {attachment_id} ({filename}) has no content URL, skipping download")
                    attachment["downloaded"] = False
                    attachment["download_error"] = "No content URL available"
                    failed_count += 1
                    continue
                
                # First check if we can access attachment metadata (helps diagnose permission issues)
                metadata = self.client.check_attachment_access(attachment_id)
                if not metadata and self.client.jira_email:
                    self.logger.debug(f"Could not access attachment metadata for {attachment_id} - may indicate permission issue")
                
                # Download the file
                file_content = self.client.download_attachment(content_url)
                
                # Sanitize filename (remove path separators and other problematic characters)
                safe_filename = filename.replace("/", "_").replace("\\", "_").replace("..", "_")
                
                # Save to attachments directory
                file_path = self.cache_manager.attachments_dir / safe_filename
                
                # Handle filename conflicts by appending attachment ID
                if file_path.exists():
                    name_parts = safe_filename.rsplit(".", 1)
                    if len(name_parts) == 2:
                        safe_filename = f"{name_parts[0]}_{attachment_id}.{name_parts[1]}"
                    else:
                        safe_filename = f"{safe_filename}_{attachment_id}"
                    file_path = self.cache_manager.attachments_dir / safe_filename
                
                # Write file
                with open(file_path, 'wb') as f:
                    f.write(file_content)
                
                # Update attachment metadata with local path
                attachment["local_path"] = str(file_path.relative_to(self.cache_manager.cache_dir))
                attachment["local_filename"] = safe_filename
                attachment["downloaded"] = True
                
                downloaded_count += 1
                self.logger.debug(f"Downloaded {filename} -> {file_path}")
                
            except Exception as e:
                attachment_id = attachment.get("id", "unknown")
                filename = attachment.get("filename", "unknown")
                error_msg = f"Failed to download attachment {attachment_id} ({filename}): {e}"
                
                # Log error with context
                if "403" in str(e) or "Forbidden" in str(e):
                    self.logger.warning(f"⚠️  Permission denied for attachment {attachment_id} ({filename})")
                    self.logger.warning(f"   This attachment may be restricted or your account lacks access")
                elif "401" in str(e) or "Unauthorized" in str(e):
                    self.logger.error(f"❌ Authentication failed for attachment {attachment_id} ({filename})")
                else:
                    self.logger.error(f"❌ {error_msg}")
                
                self.errors.append(error_msg)
                attachment["downloaded"] = False
                attachment["download_error"] = str(e)
                failed_count += 1
                # Continue with next attachment instead of stopping
        
        self.logger.info(f"Downloaded {downloaded_count} attachment(s), {failed_count} failed")
        
        if failed_count > 0:
            self.logger.warning(f"⚠️  {failed_count} attachment(s) could not be downloaded")
            self.logger.warning("   Attachment metadata is still saved - files can be downloaded later if needed")
            self.logger.warning("   Check extraction_errors.log for details")