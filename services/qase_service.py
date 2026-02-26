"""Qase API service using Python SDK."""

import time
from typing import Dict, Any, List, Optional
from pathlib import Path
import certifi

from qase.api_client_v1.api_client import ApiClient as ApiClientV1
from qase.api_client_v1.configuration import Configuration as ConfigurationV1
from qase.api_client_v1.api.projects_api import ProjectsApi
from qase.api_client_v1.api.suites_api import SuitesApi
from qase.api_client_v1.api.cases_api import CasesApi
from qase.api_client_v1.api.attachments_api import AttachmentsApi
from qase.api_client_v1.api.runs_api import RunsApi
from qase.api_client_v1.models import (
    ProjectCreate,
    SuiteCreate,
    TestCasebulk,
    TestCasebulkCasesInner,
    TestStepCreate,
    RunCreate,
)

from qase.api_client_v2.api_client import ApiClient as ApiClientV2
from qase.api_client_v2.configuration import Configuration as ConfigurationV2
from qase.api_client_v2.api.results_api import ResultsApi as ResultsApiV2
from qase.api_client_v2.models import (
    CreateResultsRequestV2,
    ResultCreate,
    ResultExecution,
    ResultStep,
    ResultStepData,
    ResultStepExecution,
    ResultStepStatus,
)

from utils.logger import get_logger

logger = get_logger(__name__)


class QaseService:
    """
    Service for interacting with Qase API using Python SDK.
    
    Handles authentication, rate limiting, and API calls for:
    - Projects
    - Suites
    - Cases
    - Attachments
    - Runs
    - Results
    """
    
    def __init__(self, api_token: str, qase_host: str = "https://api.qase.io/v1"):
        """
        Initialize Qase service with SDK clients.
        
        Args:
            api_token: Qase API token
            qase_host: Qase API base URL (default: https://api.qase.io/v1 for cloud)
                      For enterprise: https://api-<domain>/v1
                      Note: This should be the v1 base URL, v2 will be derived from it
        """
        self.api_token = api_token
        
        # Normalize host URL (remove /v1 if present, we'll add it explicitly)
        base_host = qase_host.rstrip("/")
        if base_host.endswith("/v1"):
            base_host = base_host[:-3]
        elif base_host.endswith("/v2"):
            base_host = base_host[:-3]
        
        # Setup API v1 client
        config_v1 = ConfigurationV1()
        config_v1.api_key['TokenAuth'] = api_token
        config_v1.host = f"{base_host}/v1"
        config_v1.ssl_ca_cert = certifi.where()
        self.client_v1 = ApiClientV1(config_v1)
        
        # Setup API v2 client (for results)
        config_v2 = ConfigurationV2()
        config_v2.api_key['TokenAuth'] = api_token
        config_v2.host = f"{base_host}/v2"
        config_v2.ssl_ca_cert = certifi.where()
        self.client_v2 = ApiClientV2(config_v2)
        
        # Initialize API instances
        self.projects_api = ProjectsApi(self.client_v1)
        self.suites_api = SuitesApi(self.client_v1)
        self.cases_api = CasesApi(self.client_v1)
        self.attachments_api = AttachmentsApi(self.client_v1)
        self.runs_api = RunsApi(self.client_v1)
        self.results_api_v2 = ResultsApiV2(self.client_v2)
        
        # Rate limiting: ~230 requests per 10 seconds for cloud
        self.rate_limit_delay = 0.05  # ~20 requests per second
        self.last_request_time = 0
    
    def _rate_limit(self):
        """Apply rate limiting."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - time_since_last)
        self.last_request_time = time.time()
    
    def create_project(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a project in Qase.
        
        Args:
            project_data: Project payload with title, code, description, etc.
        
        Returns:
            Created project data
        """
        self._rate_limit()
        logger.debug(f"Creating project: {project_data.get('code')}")
        
        try:
            project_create = ProjectCreate(
                title=project_data.get("title"),
                code=project_data.get("code"),
                description=project_data.get("description", ""),
                settings=project_data.get("settings", {}),
                access=project_data.get("access", "all"),
                group=project_data.get("group")
            )
            
            response = self.projects_api.create_project(project_create=project_create)
            
            if response.status:
                return {
                    "code": response.result.code,
                    "id": getattr(response.result, 'id', None)
                }
            else:
                raise Exception(f"Failed to create project: {response}")
                
        except Exception as e:
            logger.error(f"Error creating project: {e}")
            raise
    
    def upload_attachment(self, project_code: str, file_path: Path) -> Dict[str, str]:
        """
        Upload an attachment to Qase project.
        
        Args:
            project_code: Qase project code
            file_path: Path to file to upload
        
        Returns:
            Dictionary with hash, filename, url
        """
        self._rate_limit()
        logger.debug(f"Uploading attachment: {file_path.name}")
        
        try:
            # Read file content
            with open(file_path, "rb") as f:
                file_content = f.read()
            
            # SDK expects list of tuples: [(filename, content_bytes)]
            attachment_data = [(file_path.name, file_content)]
            
            response = self.attachments_api.upload_attachment(
                code=project_code,
                file=attachment_data
            )
            
            if response.status and response.result:
                attachment = response.result[0]
                return {
                    "hash": attachment.hash,
                    "filename": attachment.filename,
                    "url": attachment.url
                }
            else:
                raise Exception(f"Failed to upload attachment: {response}")
                
        except Exception as e:
            logger.error(f"Error uploading attachment: {e}")
            raise
    
    def create_suite(self, project_code: str, suite_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a suite in Qase.
        
        Args:
            project_code: Qase project code
            suite_data: Suite payload with title, description, parent_id, etc.
        
        Returns:
            Created suite data with ID
        """
        self._rate_limit()
        logger.debug(f"Creating suite: {suite_data.get('title')}")
        
        try:
            suite_create = SuiteCreate(
                title=suite_data.get("title"),
                description=suite_data.get("description", ""),
                preconditions=suite_data.get("preconditions", ""),
                parent_id=suite_data.get("parent_id")
            )
            
            response = self.suites_api.create_suite(
                code=project_code,
                suite_create=suite_create
            )
            
            if response.status:
                return {
                    "id": response.result.id
                }
            else:
                raise Exception(f"Failed to create suite: {response}")
                
        except Exception as e:
            logger.error(f"Error creating suite: {e}")
            raise
    
    def create_cases_bulk(self, project_code: str, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Bulk create cases in Qase.
        
        Args:
            project_code: Qase project code
            cases: List of case payloads (max 100 per request)
        
        Returns:
            Response with created cases
        """
        self._rate_limit()
        logger.debug(f"Bulk creating {len(cases)} cases")
        
        try:
            # Convert dict cases to SDK models
            case_models = []
            for case_data in cases:
                # Convert steps if present
                steps = []
                if case_data.get("steps"):
                    for step_data in case_data["steps"]:
                        step = TestStepCreate(
                            action=step_data.get("action", ""),
                            expected_result=step_data.get("expected_result", ""),
                            data=step_data.get("data", ""),
                            position=step_data.get("position", 0)
                        )
                        steps.append(step)
                
                # Handle params: SDK expects dict, but we'll omit if empty to avoid validation issues
                params_value = case_data.get("params")
                if params_value and isinstance(params_value, dict):
                    # If params is a dict, use it
                    params_final = params_value
                elif params_value and isinstance(params_value, list) and len(params_value) > 0:
                    # If params is a non-empty list, convert to dict format if needed
                    # For now, omit it if it's a list (SDK expects dict)
                    params_final = None
                else:
                    # Empty or None - omit the field
                    params_final = None
                
                # Build case model, only include params if it's a valid dict
                case_model_data = {
                    "id": case_data.get("id"),  # Optional, for preserve_ids
                    "title": case_data.get("title"),
                    "description": case_data.get("description", ""),
                    "preconditions": case_data.get("preconditions", ""),
                    "postconditions": case_data.get("postconditions", ""),
                    "severity": case_data.get("severity"),
                    "priority": case_data.get("priority"),
                    "type": case_data.get("type"),
                    "behavior": case_data.get("behavior"),
                    "automation": case_data.get("automation", 0),
                    "status": case_data.get("status", 1),
                    "suite_id": case_data.get("suite_id"),
                    "milestone_id": case_data.get("milestone_id"),
                    "author_id": case_data.get("author_id"),
                    "created_at": case_data.get("created_at"),
                    "updated_at": case_data.get("updated_at"),
                    "steps": steps if steps else None,
                    "attachments": case_data.get("attachments", []),
                    "custom_field": case_data.get("custom_field", {}),
                    "is_flaky": case_data.get("is_flaky", 0)
                }
                
                # Only add params if it's a valid dict
                if params_final is not None:
                    case_model_data["params"] = params_final
                
                case_model = TestCasebulkCasesInner(**case_model_data)
                case_models.append(case_model)
            
            test_case_bulk = TestCasebulk(cases=case_models)
            response = self.cases_api.bulk(
                code=project_code,
                test_casebulk=test_case_bulk
            )
            
            if response.status:
                # Convert response to dict format
                # The response structure may vary - check what's actually available
                created_cases = []
                if response.result:
                    # Try different possible response structures
                    if hasattr(response.result, 'cases') and response.result.cases:
                        # If result has cases attribute
                        for case in response.result.cases:
                            created_cases.append({
                                "id": getattr(case, 'id', None),
                                "title": getattr(case, 'title', None)
                            })
                    elif hasattr(response.result, 'ids') and response.result.ids:
                        # If result has ids array (bulk response)
                        for case_id in response.result.ids:
                            created_cases.append({
                                "id": case_id,
                                "title": None  # Title not in ids-only response
                            })
                    # If no cases in response, cases were still created successfully
                    # We'll return empty list but cases are in Qase
                return {"cases": created_cases}
            else:
                raise Exception(f"Failed to create cases: {response}")
                
        except Exception as e:
            logger.error(f"Error creating cases: {e}")
            raise
    
    def create_run(self, project_code: str, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a test run in Qase.
        
        Args:
            project_code: Qase project code
            run_data: Run payload with title, cases, etc.
        
        Returns:
            Created run data with ID
        """
        self._rate_limit()
        logger.debug(f"Creating run: {run_data.get('title')}")
        
        try:
            run_create = RunCreate(
                title=run_data.get("title"),
                description=run_data.get("description", ""),
                start_time=run_data.get("start_time"),
                end_time=run_data.get("end_time"),
                author_id=run_data.get("author_id"),
                cases=run_data.get("cases", []),
                configurations=run_data.get("configurations", []),
                milestone_id=run_data.get("milestone_id")
            )
            
            response = self.runs_api.create_run(
                code=project_code,
                run_create=run_create
            )
            
            if response.status:
                return {
                    "id": response.result.id,
                    "title": response.result.title
                }
            else:
                raise Exception(f"Failed to create run: {response}")
                
        except Exception as e:
            logger.error(f"Error creating run: {e}")
            raise
    
    def create_results_bulk_v2(
        self,
        project_code: str,
        run_id: int,
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Bulk create results in Qase (API v2).
        
        Args:
            project_code: Qase project code
            run_id: Run ID
            results: List of result payloads (max 500 per request)
        
        Returns:
            Response with created results
        """
        self._rate_limit()
        logger.debug(f"Bulk creating {len(results)} results for run {run_id}")
        
        try:
            # Convert dict results to SDK models
            result_models = []
            for result_data in results:
                # Convert execution data
                execution_data = result_data.get("execution", {})
                execution = ResultExecution(
                    status=execution_data.get("status"),
                    duration=execution_data.get("duration"),
                    start_time=execution_data.get("start_time"),
                    end_time=execution_data.get("end_time")
                )
                
                # Convert steps if present
                steps = []
                if result_data.get("steps"):
                    for step_data in result_data["steps"]:
                        step_exec_data = step_data.get("execution", {})
                        step_data_obj = step_data.get("data", {})
                        
                        # Map status string to enum
                        status_str = step_exec_data.get("status", "").upper()
                        try:
                            # Try to get enum value (PASSED, FAILED, BLOCKED, SKIPPED)
                            step_status = getattr(ResultStepStatus, status_str, None)
                            if step_status is None:
                                # Fallback: try common mappings
                                status_map = {
                                    "PASSED": ResultStepStatus.PASSED,
                                    "FAILED": ResultStepStatus.FAILED,
                                    "BLOCKED": ResultStepStatus.BLOCKED,
                                    "SKIPPED": ResultStepStatus.SKIPPED
                                }
                                step_status = status_map.get(status_str, ResultStepStatus.PASSED)
                        except (AttributeError, ValueError):
                            # If enum doesn't exist or conversion fails, default to PASSED
                            step_status = ResultStepStatus.PASSED
                        
                        step = ResultStep(
                            data=ResultStepData(
                                action=step_data_obj.get("action", ""),
                                expected_result=step_data_obj.get("expected_result", "")
                            ),
                            execution=ResultStepExecution(
                                status=step_status,
                                comment=step_exec_data.get("comment", "")
                            )
                        )
                        steps.append(step)
                
                result_model = ResultCreate(
                    title=result_data.get("title"),
                    testops_id=result_data.get("testops_id"),
                    execution=execution,
                    message=result_data.get("message", ""),
                    attachments=result_data.get("attachments", []),
                    steps=steps if steps else None
                )
                result_models.append(result_model)
            
            request = CreateResultsRequestV2(results=result_models)
            response = self.results_api_v2.create_results_v2(
                project_code=project_code,
                run_id=run_id,
                create_results_request_v2=request
            )
            
            if response.status:
                return {"status": "success"}
            else:
                raise Exception(f"Failed to create results: {response}")
                
        except Exception as e:
            logger.error(f"Error creating results: {e}")
            raise
    
    def complete_run(self, project_code: str, run_id: int) -> Dict[str, Any]:
        """
        Complete a test run in Qase.
        
        Args:
            project_code: Qase project code
            run_id: Run ID
        
        Returns:
            Response data
        """
        self._rate_limit()
        logger.debug(f"Completing run {run_id}")
        
        try:
            response = self.runs_api.complete_run(
                code=project_code,
                id=run_id
            )
            
            if response.status:
                return {"status": "success"}
            else:
                raise Exception(f"Failed to complete run: {response}")
                
        except Exception as e:
            logger.error(f"Error completing run: {e}")
            raise
