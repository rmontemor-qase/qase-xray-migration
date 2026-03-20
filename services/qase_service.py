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
                raw_title = case_data.get("title")
                if isinstance(raw_title, str):
                    title = raw_title.strip()
                elif raw_title is not None:
                    title = str(raw_title).strip()
                else:
                    title = ""
                if len(title) > 255:
                    title = title[:252].rstrip() + "..."
                if not title:
                    title = "Untitled test case"
                # Convert steps if present
                steps = []
                if case_data.get("steps"):
                    for step_data in case_data["steps"]:
                        action = (step_data.get("action") or "").strip()
                        expected = (step_data.get("expected_result") or "").strip()
                        data = step_data.get("data", "")
                        if not isinstance(data, str):
                            data = str(data) if data is not None else ""
                        data = data.strip()
                        if not action and not expected and not data:
                            continue
                        if not action:
                            action = "."
                        step = TestStepCreate(
                            action=action,
                            expected_result=expected,
                            data=data,
                            position=len(steps) + 1,
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
                raw_tags = case_data.get("tags")
                if isinstance(raw_tags, list) and raw_tags:
                    tags_out = [str(t).strip() for t in raw_tags if t is not None and str(t).strip()]
                else:
                    tags_out = None

                requested_id: Optional[int] = None
                raw_case_id = case_data.get("id")
                if raw_case_id is not None:
                    try:
                        requested_id = int(raw_case_id)
                    except (TypeError, ValueError):
                        logger.warning(
                            "Bulk case %r: ignoring invalid id %r (expected integer)",
                            title,
                            raw_case_id,
                        )

                case_model_data = {
                    "id": requested_id,
                    "title": title,
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
                    "tags": tags_out,
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
                created_cases = []
                created_ids: List[Any] = []
                if response.result:
                    if hasattr(response.result, "cases") and response.result.cases:
                        for case in response.result.cases:
                            created_cases.append({
                                "id": getattr(case, "id", None),
                                "title": getattr(case, "title", None),
                            })
                            cid = getattr(case, "id", None)
                            if cid is not None:
                                created_ids.append(cid)
                    elif hasattr(response.result, "ids") and response.result.ids:
                        created_ids = list(response.result.ids)
                        for case_id in created_ids:
                            created_cases.append({"id": case_id, "title": None})
                requested = len(case_models)
                got = len(created_ids) if created_ids else len(created_cases)
                if got == 0 and requested > 0 and response.result:
                    logger.warning(
                        "Bulk case create succeeded but no ids/cases in response; "
                        "cannot verify how many cases were created."
                    )
                if got != requested:
                    logger.warning(
                        "Bulk case create: Qase returned %s id(s) for %s case(s) sent. "
                        "Unreturned items were likely skipped by the API (e.g. duplicate title).",
                        got,
                        requested,
                    )
                return {
                    "cases": created_cases,
                    "ids": created_ids,
                    "requested": requested,
                    "created_count": got,
                }
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
                res = response.result
                return {
                    "id": getattr(res, "id", None),
                    "title": getattr(res, "title", None) or run_data.get("title"),
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
        run_id_int = int(run_id)
        logger.debug(f"Bulk creating {len(results)} results for run {run_id_int}")
        
        try:
            # Convert dict results to SDK models
            result_models = []
            for result_data in results:
                # Convert execution data
                execution_data = result_data.get("execution", {})
                exec_status = execution_data.get("status")
                if not exec_status or not isinstance(exec_status, str):
                    exec_status = "passed"
                # Qase validates result execution times against the run start (often ~"now" when
                # the run was just created). Xray exports real historical startedOn/finishedOn,
                # which are always in the past vs that anchor → 422 "must be at least <unix>".
                # Keep duration (and status); omit absolute timestamps for migration.
                execution = ResultExecution(
                    status=exec_status,
                    duration=execution_data.get("duration"),
                    start_time=None,
                    end_time=None,
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
                        
                        action = (step_data_obj.get("action") or "").strip()
                        if not action:
                            action = "."
                        step_att = step_exec_data.get("attachments") or []
                        step_att_list = (
                            [str(x) for x in step_att if x is not None]
                            if isinstance(step_att, list)
                            else []
                        )
                        step = ResultStep(
                            data=ResultStepData(
                                action=action,
                                expected_result=step_data_obj.get("expected_result") or ""
                            ),
                            execution=ResultStepExecution(
                                status=step_status,
                                comment=step_exec_data.get("comment") or None,
                                attachments=step_att_list or None,
                            )
                        )
                        steps.append(step)
                
                raw_title = result_data.get("title")
                title = (
                    raw_title.strip()
                    if isinstance(raw_title, str)
                    else (str(raw_title).strip() if raw_title is not None else "")
                )
                if not title:
                    title = "Test result"
                result_model = ResultCreate(
                    title=title,
                    testops_id=result_data.get("testops_id"),
                    execution=execution,
                    message=result_data.get("message") or "",
                    attachments=result_data.get("attachments") or [],
                    steps=steps if steps else None
                )
                result_models.append(result_model)
            
            request = CreateResultsRequestV2(results=result_models)
            api_resp = self.results_api_v2.create_results_v2_with_http_info(
                project_code=project_code,
                run_id=run_id_int,
                create_results_request_v2=request,
            )
            # 202 + empty body → deserialized `data` can be None; do not touch .status on None
            if api_resp.status_code not in (200, 202):
                raise Exception(
                    f"Failed to create results: HTTP {api_resp.status_code} {api_resp.raw_data!r}"
                )
            body = api_resp.data
            if body is not None and getattr(body, "status", None) is False:
                raise Exception(f"Failed to create results: {body}")
            return {"status": "success"}
                
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
