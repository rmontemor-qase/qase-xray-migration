"""Repository for accessing Xray Cloud GraphQL API."""

from typing import List, Dict, Any, Optional
from tqdm import tqdm

from utils.graphql_client import GraphQLClient
from utils.logger import get_logger
from models.xray_models import (
    XrayProject,
    XrayFolder,
    XrayTest,
    XrayTestExecution,
    XrayTestRun,
    XrayTestStep,
    XrayTestRunStep,
)

logger = get_logger(__name__)


class XrayCloudRepository:
    """
    Repository for accessing Xray Cloud data via GraphQL API.
    
    Handles pagination, data transformation, and error handling.
    """
    
    # GraphQL query limits
    MAX_LIMIT = 100  # Max items per query
    MAX_TOTAL = 10000  # Max total items per call
    
    def __init__(self, graphql_client: GraphQLClient):
        """
        Initialize repository with GraphQL client.
        
        Args:
            graphql_client: Configured GraphQLClient instance
        """
        self.client = graphql_client
    
    def get_projects(self, project_keys: List[str]) -> List[Dict[str, Any]]:
        """
        Get project information from Jira REST API.
        
        Args:
            project_keys: List of project keys to fetch
        
        Returns:
            List of project data dictionaries
        """
        logger.info(f"Fetching {len(project_keys)} projects from Jira...")
        projects = []
        
        for key in tqdm(project_keys, desc="Fetching projects"):
            try:
                # Use Jira REST API to get project details
                project_data = self.client.get_jira_rest_api(f"/rest/api/3/project/{key}")
                projects.append(project_data)
            except Exception as e:
                logger.error(f"Failed to fetch project {key}: {e}")
                # Continue with other projects
        
        logger.info(f"Fetched {len(projects)} projects")
        return projects
    
    def get_tests(
        self,
        project_key: str,
        folder_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all tests for a project using GraphQL.
        
        Args:
            project_key: Jira project key
            folder_path: Optional folder path to filter tests
        
        Returns:
            List of test data dictionaries
        """
        logger.info(f"Fetching tests for project {project_key}...")
        
        all_tests = []
        start = 0
        limit = self.MAX_LIMIT
        
        # Build JQL query
        jql = f"project = '{project_key}'"
        if folder_path:
            jql += f" AND folder = '{folder_path}'"
        
        query = """
        query GetTests($jql: String!, $limit: Int!, $start: Int!) {
          getTests(jql: $jql, limit: $limit, start: $start) {
            total
            start
            limit
            results {
              issueId
              projectId
              testType {
                name
              }
              folder {
                path
              }
              steps {
                id
                data
                action
                result
              }
              jira(fields: ["summary", "description", "labels", "attachment"])
            }
          }
        }
        """
        
        while True:
            try:
                variables = {
                    "jql": jql,
                    "limit": limit,
                    "start": start
                }
                
                response = self.client.execute_query(query, variables)
                tests_data = response.get("getTests", {})
                
                results = tests_data.get("results", [])
                total = tests_data.get("total", 0)
                start_pos = tests_data.get("start", start)
                limit_val = tests_data.get("limit", limit)
                
                all_tests.extend(results)
                
                logger.info(f"Page: start={start_pos}, limit={limit_val}, fetched={len(results)}, total_fetched={len(all_tests)}, API_total={total}")
                logger.debug(f"Fetched {len(results)} tests (total fetched: {len(all_tests)}, API total: {total})")
                
                # Check if we've fetched all tests
                # If we got fewer results than requested, we're done (last page)
                if len(results) < limit:
                    logger.debug(f"Got fewer results ({len(results)}) than limit ({limit}), pagination complete")
                    break
                
                # If we've fetched at least as many as the API says exist, we're done
                if total > 0 and len(all_tests) >= total:
                    logger.debug(f"Fetched all {total} tests according to API")
                    break
                
                # If no more results, we're done
                if len(results) == 0:
                    logger.debug("No more results, pagination complete")
                    break
                
                start += limit
                
                # Safety check to prevent infinite loops
                if start >= self.MAX_TOTAL:
                    logger.warning(f"Reached maximum limit of {self.MAX_TOTAL} tests")
                    break
                    
            except Exception as e:
                logger.error(f"Error fetching tests (start={start}): {e}")
                break
        
        logger.info(f"Fetched {len(all_tests)} tests for project {project_key}")
        return all_tests
    
    def get_test_executions(
        self,
        project_key: str
    ) -> List[Dict[str, Any]]:
        """
        Get all test executions for a project using GraphQL.
        
        Args:
            project_key: Jira project key
        
        Returns:
            List of test execution data dictionaries
        """
        logger.info(f"Fetching test executions for project {project_key}...")
        
        all_executions = []
        start = 0
        limit = 50  # Smaller limit for executions as they contain nested test runs
        
        jql = f"project = '{project_key}'"
        
        query = """
        query GetTestExecutions($jql: String!, $limit: Int!, $start: Int!) {
          getTestExecutions(jql: $jql, limit: $limit, start: $start) {
            total
            results {
              issueId
              projectId
              testRuns(limit: 100) {
                total
                results {
                  id
                  status {
                    name
                    color
                  }
                  startedOn
                  finishedOn
                  test {
                    issueId
                  }
                  comment
                  steps {
                    status {
                      name
                    }
                    actualResult
                    comment
                  }
                }
              }
              jira(fields: ["summary", "description"])
            }
          }
        }
        """
        
        while True:
            try:
                variables = {
                    "jql": jql,
                    "limit": limit,
                    "start": start
                }
                
                response = self.client.execute_query(query, variables)
                executions_data = response.get("getTestExecutions", {})
                
                results = executions_data.get("results", [])
                total = executions_data.get("total", 0)
                
                all_executions.extend(results)
                
                logger.debug(f"Fetched {len(results)} test executions (total fetched: {len(all_executions)}, API total: {total})")
                
                # Check if we've fetched all executions
                if len(results) < limit:
                    logger.debug(f"Got fewer results ({len(results)}) than limit ({limit}), pagination complete")
                    break
                if total > 0 and len(all_executions) >= total:
                    logger.debug(f"Fetched all {total} executions according to API")
                    break
                if len(results) == 0:
                    logger.debug("No more results, pagination complete")
                    break
                
                start += limit
                
                # Safety check
                if start >= self.MAX_TOTAL:
                    logger.warning(f"Reached maximum limit of {self.MAX_TOTAL} test executions")
                    break
                    
            except Exception as e:
                logger.error(f"Error fetching test executions (start={start}): {e}")
                break
        
        logger.info(f"Fetched {len(all_executions)} test executions for project {project_key}")
        return all_executions
    
    def get_folders(
        self,
        project_id: str,
        base_path: str = "/"
    ) -> List[Dict[str, Any]]:
        """
        Get folders for a project recursively.
        
        Args:
            project_id: Xray project ID
            base_path: Base folder path to start from (default: "/")
        
        Returns:
            List of folder data dictionaries
        """
        logger.info(f"Fetching folders for project {project_id} (path: {base_path})...")
        
        folders = []
        
        query = """
        query GetFolder($projectId: String!, $path: String!) {
          getFolder(projectId: $projectId, path: $path) {
            name
            path
            testsCount
            folders {
              name
              path
              testsCount
            }
          }
        }
        """
        
        def fetch_folder_recursive(path: str):
            """Recursively fetch folders."""
            try:
                variables = {
                    "projectId": project_id,
                    "path": path
                }
                
                response = self.client.execute_query(query, variables)
                folder_data = response.get("getFolder")
                
                if folder_data:
                    folders.append(folder_data)
                    
                    # Recursively fetch subfolders
                    subfolders = folder_data.get("folders", [])
                    if subfolders:
                        logger.debug(f"Found {len(subfolders)} subfolders in {path}")
                        for subfolder in subfolders:
                            subfolder_path = subfolder.get("path", "")
                            if subfolder_path:
                                fetch_folder_recursive(subfolder_path)
                    else:
                        logger.debug(f"No subfolders found in {path}")
                else:
                    logger.warning(f"No folder data returned for path: {path}, project: {project_id}")
                        
            except Exception as e:
                logger.error(f"Error fetching folder {path} for project {project_id}: {e}")
                logger.debug(f"Folder query variables: projectId={project_id}, path={path}", exc_info=True)
        
        try:
            fetch_folder_recursive(base_path)
        except Exception as e:
            logger.error(f"Error fetching folders: {e}")
        
        logger.info(f"Fetched {len(folders)} folders for project {project_id}")
        return folders
    
    def get_attachments(self, attachment_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Get attachment metadata and download attachments from Jira REST API.
        
        Args:
            attachment_ids: List of attachment IDs
        
        Returns:
            List of attachment data dictionaries
        """
        logger.info(f"Fetching {len(attachment_ids)} attachments...")
        
        attachments = []
        
        for attachment_id in tqdm(attachment_ids, desc="Fetching attachments"):
            try:
                # Get attachment metadata from Jira REST API
                attachment_data = self.client.get_jira_rest_api(
                    f"/rest/api/3/attachment/{attachment_id}"
                )
                attachments.append(attachment_data)
            except Exception as e:
                logger.error(f"Failed to fetch attachment {attachment_id}: {e}")
                # Continue with other attachments
        
        logger.info(f"Fetched {len(attachments)} attachments")
        return attachments
