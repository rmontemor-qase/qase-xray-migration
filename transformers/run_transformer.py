"""Transformer for Xray test executions and runs to Qase runs and results."""

from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from utils.cache_manager import CacheManager
from utils.logger import get_logger
from models.mappings import MappingStore
from transformers.xray_transformer import BaseTransformer

logger = get_logger(__name__)


class RunTransformer(BaseTransformer):
    """Transforms Xray test executions to Qase runs and results."""
    
    def transform(
        self,
        executions_data: List[Dict[str, Any]],
        qase_cases: Dict[str, List[Dict[str, Any]]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Transform Xray test executions to Qase runs and results.
        
        Args:
            executions_data: List of Xray test execution data
            qase_cases: Dictionary mapping project_code → list of cases
        
        Returns:
            Tuple of (list of run payloads, list of result payloads)
        """
        qase_runs = []
        qase_results = []
        
        # Build case ID mapping (Xray issue ID → Qase case ID)
        xray_to_qase_case: Dict[str, Dict[str, int]] = {}  # project_code → {xray_id → qase_id}
        
        for project_code, cases in qase_cases.items():
            xray_to_qase_case[project_code] = {}
            for idx, case in enumerate(cases):
                xray_id = case.get("_xray_issue_id")
                if xray_id:
                    # Qase case ID will be set after creation, for now use index
                    xray_to_qase_case[project_code][str(xray_id)] = idx
        
        for execution in executions_data:
            try:
                project_id = str(execution.get("projectId", ""))
                project_code = self.mappings.get_qase_id(project_id)
                
                if not project_code:
                    continue
                
                # Transform execution to run
                qase_run = self._transform_execution_to_run(execution, project_code)
                if not qase_run:
                    continue
                
                qase_runs.append(qase_run)
                
                # Transform test runs to results
                test_runs = execution.get("testRuns", {}).get("results", [])
                for test_run in test_runs:
                    qase_result = self._transform_test_run_to_result(
                        test_run,
                        execution,
                        project_code,
                        xray_to_qase_case.get(project_code, {})
                    )
                    
                    if qase_result:
                        qase_results.append(qase_result)
                
            except Exception as e:
                self.logger.error(f"Error transforming execution {execution.get('issueId')}: {e}")
                continue
        
        self.logger.info(f"Transformed {len(qase_runs)} runs and {len(qase_results)} results")
        return qase_runs, qase_results
    
    def _transform_execution_to_run(
        self,
        execution: Dict[str, Any],
        project_code: str
    ) -> Optional[Dict[str, Any]]:
        """
        Transform a single Xray execution to Qase run.
        
        Args:
            execution: Xray test execution data
            project_code: Qase project code
        
        Returns:
            Qase run payload or None if transformation fails
        """
        jira_data = execution.get("jira", {})
        summary = jira_data.get("summary", "")
        description_doc = jira_data.get("description", {})
        
        description = ""
        if description_doc:
            description = self.convert_jira_doc_to_markdown(description_doc)
        
        test_runs = execution.get("testRuns", {}).get("results", [])
        
        # Collect case IDs for this run
        case_ids = []
        for test_run in test_runs:
            test_issue_id = test_run.get("test", {}).get("issueId", "")
            if test_issue_id:
                # Case ID will be resolved during load phase
                case_ids.append(test_issue_id)
        
        if not case_ids:
            return None
        
        # Create run
        qase_run = {
            "title": summary,
            "description": description,
            "cases": case_ids,
            "start_time": None,  # Will be set from test runs
            "end_time": None,
            "_execution_issue_id": execution.get("issueId"),
            "_project_code": project_code
        }
        
        return qase_run
    
    def _transform_test_run_to_result(
        self,
        test_run: Dict[str, Any],
        execution: Dict[str, Any],
        project_code: str,
        xray_to_qase_case: Dict[str, int]
    ) -> Optional[Dict[str, Any]]:
        """
        Transform a single Xray test run to Qase result.
        
        Args:
            test_run: Xray test run data
            execution: Parent execution data
            project_code: Qase project code
            xray_to_qase_case: Mapping of Xray test ID → Qase case index
        
        Returns:
            Qase result payload or None if transformation fails
        """
        test_issue_id = test_run.get("test", {}).get("issueId", "")
        qase_case_id = xray_to_qase_case.get(str(test_issue_id))
        
        if qase_case_id is None:
            return None
        
        status = test_run.get("status", {}).get("name", "").lower()
        qase_status = self._map_xray_status_to_qase(status)
        
        if qase_status == "skipped":  # Skip untested
            return None
        
        started_on = test_run.get("startedOn")
        finished_on = test_run.get("finishedOn")
        
        # Convert timestamps
        start_time = None
        end_time = None
        duration = 0
        
        if started_on:
            try:
                start_time = int(datetime.fromisoformat(started_on.replace("Z", "+00:00")).timestamp())
            except:
                pass
        
        if finished_on:
            try:
                end_time = int(datetime.fromisoformat(finished_on.replace("Z", "+00:00")).timestamp())
            except:
                pass
        
        if start_time and end_time:
            duration = (end_time - start_time) * 1000  # Convert to milliseconds
        elif start_time:
            duration = 5000  # Default 5 seconds if no end time
            end_time = start_time + 5
        
        comment = test_run.get("comment", "")
        
        # Process step results
        step_results = []
        steps = test_run.get("steps", [])
        
        for step in steps:
            step_status = step.get("status", {}).get("name", "").lower()
            qase_step_status = self._map_xray_status_to_qase(step_status)
            
            if qase_step_status == "skipped":
                continue
            
            actual_result = step.get("actualResult", "")
            step_comment = step.get("comment", "")
            
            step_result = {
                "data": {
                    "action": "",  # Will be matched with case step
                    "expected_result": ""
                },
                "execution": {
                    "status": qase_step_status,
                    "comment": step_comment or actual_result or ""
                }
            }
            step_results.append(step_result)
        
        execution_summary = execution.get("jira", {}).get("summary", "")
        
        qase_result = {
            "title": execution_summary,  # Will use case title
            "testops_id": qase_case_id,
            "execution": {
                "status": qase_status,
                "duration": duration,
                "start_time": start_time or int(datetime.now().timestamp()),
                "end_time": end_time or (start_time or int(datetime.now().timestamp())) + 5
            },
            "message": comment or "",
            "attachments": [],
            "steps": step_results if step_results else None
        }
        
        return qase_result
    
    def _map_xray_status_to_qase(self, xray_status: str) -> str:
        """
        Map Xray status to Qase status.
        
        Args:
            xray_status: Xray status name (lowercase)
        
        Returns:
            Qase status: "passed", "failed", "blocked", or "skipped"
        """
        status_lower = xray_status.lower()
        
        if status_lower in ["passed", "pass"]:
            return "passed"
        elif status_lower in ["failed", "fail"]:
            return "failed"
        elif status_lower in ["blocked", "block"]:
            return "blocked"
        else:
            return "skipped"
