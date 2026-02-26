"""Transformer for Xray test cases to Qase cases."""

from typing import Dict, Any, List, Optional
from utils.cache_manager import CacheManager
from utils.logger import get_logger
from models.mappings import MappingStore
from transformers.xray_transformer import BaseTransformer

logger = get_logger(__name__)


class CaseTransformer(BaseTransformer):
    """Transforms Xray test cases to Qase cases."""
    
    def transform(
        self,
        test_cases_data: List[Dict[str, Any]],
        qase_suites: Dict[str, List[Dict[str, Any]]],
        attachments_map: Dict[str, Dict[str, str]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Transform Xray test cases to Qase cases.
        
        Args:
            test_cases_data: List of Xray test case data
            qase_suites: Dictionary mapping project_code → list of suites
            attachments_map: Map of Xray attachment ID → Qase attachment object
        
        Returns:
            Dictionary mapping project_code → list of case payloads
        """
        # Group cases by project
        project_cases: Dict[str, List[Dict[str, Any]]] = {}
        
        for test_case in test_cases_data:
            try:
                project_id = str(test_case.get("projectId", ""))
                
                # Get project code from mapping
                project_code = self.mappings.get_qase_id(project_id)
                if not project_code:
                    # Debug: Check what mappings are available
                    available_ids = list(self.mappings.mappings.keys())
                    self.logger.warning(
                        f"Project {project_id} not found in mappings. "
                        f"Available mappings: {available_ids}. Skipping case."
                    )
                    continue
                
                if project_code not in project_cases:
                    project_cases[project_code] = []
                
                # Transform test case
                qase_case = self._transform_single_case(
                    test_case,
                    qase_suites.get(project_code, []),
                    attachments_map
                )
                
                if qase_case:
                    project_cases[project_code].append(qase_case)
                
            except Exception as e:
                self.logger.error(f"Error transforming test case {test_case.get('issueId')}: {e}")
                continue
        
        total_cases = sum(len(cases) for cases in project_cases.values())
        self.logger.info(f"Transformed {total_cases} test cases across {len(project_cases)} projects")
        
        return project_cases
    
    def _transform_single_case(
        self,
        test_case: Dict[str, Any],
        suites: List[Dict[str, Any]],
        attachments_map: Dict[str, Dict[str, str]]
    ) -> Optional[Dict[str, Any]]:
        """
        Transform a single Xray test case to Qase case format.
        
        Args:
            test_case: Xray test case data
            suites: List of suites for the project
            attachments_map: Map of attachment IDs
        
        Returns:
            Qase case payload or None if transformation fails
        """
        jira_data = test_case.get("jira", {})
        summary = jira_data.get("summary", "")
        description_doc = jira_data.get("description", {})
        
        # Convert description to markdown
        description = ""
        if description_doc:
            description = self.convert_jira_doc_to_markdown(description_doc)
        
        # Process steps
        steps = []
        xray_steps = test_case.get("steps", [])
        case_attachments = []
        
        for step in xray_steps:
            action = step.get("action", "")
            result = step.get("result", "")
            data = step.get("data", "")
            
            # Process attachments in step content
            action_processed, action_attachments = self.replace_attachment_references(
                action, attachments_map
            )
            result_processed, result_attachments = self.replace_attachment_references(
                result, attachments_map
            )
            
            case_attachments.extend(action_attachments)
            case_attachments.extend(result_attachments)
            
            qase_step = {
                "action": action_processed or "",
                "expected_result": result_processed or "",
                "data": data or "",
                "position": len(steps) + 1
            }
            steps.append(qase_step)
        
        # Process case-level attachments
        # Store Xray attachment IDs - will be resolved to hashes after upload
        xray_attachment_ids = []
        jira_attachments = jira_data.get("attachment", [])
        for att_ref in jira_attachments:
            if isinstance(att_ref, str):
                att_id = att_ref
                xray_attachment_ids.append(att_id)
                # If hash already available, add it
                att_data = attachments_map.get(att_id)
                if att_data and att_data.get("hash"):
                    case_attachments.append(att_data["hash"])
            elif isinstance(att_ref, dict):
                att_id = str(att_ref.get("id", att_ref.get("attachmentId", "")))
                xray_attachment_ids.append(att_id)
                # If hash already available, add it
                att_data = attachments_map.get(att_id)
                if att_data and att_data.get("hash"):
                    case_attachments.append(att_data["hash"])
        
        # Process attachments in description
        desc_processed, desc_attachments = self.replace_attachment_references(
            description, attachments_map
        )
        description = desc_processed
        case_attachments.extend(desc_attachments)
        
        # Remove duplicate attachments
        case_attachments = list(set(case_attachments))
        
        # Find suite ID (match by folder path)
        folder_path = test_case.get("folder", {}).get("path", "")
        suite_id = None
        
        if folder_path and suites:
            # Find matching suite by path
            for suite in suites:
                suite_desc = suite.get("description", "")
                if folder_path in suite_desc:
                    # Suite ID will be set after creation, for now we track path
                    suite_id = suite.get("_suite_id")
                    break
        
        # Map test type
        test_type = test_case.get("testType", {}).get("name", "Manual")
        automation = 0  # Manual by default
        if test_type.lower() in ["automated", "automation", "cucumber", "gherkin"]:
            automation = 1
        
        # Extract labels
        labels = jira_data.get("labels", [])
        if isinstance(labels, str):
            labels = [l.strip() for l in labels.split(",")]
        
        qase_case = {
            "title": summary,
            "description": description,
            "preconditions": "",
            "postconditions": "",
            "severity": 2,  # Normal (default)
            "priority": 1,  # Low (default)
            "type": 1,      # Functional (default)
            "behavior": 1,   # Positive (default)
            "automation": automation,
            "status": 1,     # Actual (default)
            "suite_id": suite_id,  # Will be set after suite creation
            "steps": steps,
            "attachments": case_attachments,  # Hashes if available, will be updated after upload
            "tags": labels,  # Qase uses tags for labels
            "_xray_issue_id": test_case.get("issueId"),  # Store for reference
            "_folder_path": folder_path,  # Store for suite matching
            "_xray_attachment_ids": list(set(xray_attachment_ids))  # Store Xray IDs for later resolution
        }
        
        return qase_case
