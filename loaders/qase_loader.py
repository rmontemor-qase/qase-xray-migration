"""Loader for importing transformed data into Qase."""

import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from tqdm import tqdm

from services.qase_service import QaseService
from utils.cache_manager import CacheManager
from utils.logger import get_logger
from models.mappings import MappingStore

logger = get_logger(__name__)


class QaseLoader:
    """
    Loads transformed data into Qase.
    
    Loads in order:
    1. Projects
    2. Attachments (upload and update mappings)
    3. Suites (hierarchical)
    4. Cases (bulk)
    5. Runs
    6. Results (bulk)
    """
    
    def __init__(
        self,
        cache_manager: CacheManager,
        qase_service: QaseService,
        mappings: MappingStore
    ):
        """
        Initialize loader.
        
        Args:
            cache_manager: CacheManager instance for reading transformed data
            qase_service: QaseService instance for API calls
            mappings: MappingStore for tracking ID mappings
        """
        self.cache_manager = cache_manager
        self.qase_service = qase_service
        self.mappings = mappings
        
        self.stats = {
            "projects": 0,
            "attachments": 0,
            "suites": 0,
            "cases": 0,
            "runs": 0,
            "results": 0,
            "errors": 0
        }
    
    def load(self) -> Dict[str, Any]:
        """
        Load all transformed data into Qase.
        
        Returns:
            Dictionary with loading statistics
        """
        logger.info("Starting Qase data import...")
        
        try:
            # Load transformed data
            transformed_dir = self.cache_manager.cache_dir / "transformed"
            if not transformed_dir.exists():
                raise ValueError(f"Transformed data directory not found: {transformed_dir}")
            
            projects = self._load_json(transformed_dir / "projects.json")
            suites = self._load_json(transformed_dir / "suites.json")
            cases = self._load_json(transformed_dir / "cases.json")
            attachments_map = self._load_json(transformed_dir / "attachments_map.json")
            runs = self._load_json(transformed_dir / "runs.json") or []
            results = self._load_json(transformed_dir / "results.json") or []
            
            # Load in order
            logger.info("Step 1: Creating projects...")
            self._load_projects(projects)
            
            logger.info("Step 2: Uploading attachments...")
            self._load_attachments(attachments_map)
            
            logger.info("Step 3: Updating cases with attachment hashes...")
            self._update_cases_with_attachment_hashes(cases, attachments_map)
            
            logger.info("Step 4: Creating suites...")
            suite_maps = self._load_suites(suites)
            
            logger.info("Step 5: Creating cases...")
            self._load_cases(cases, suite_maps)
            
            if runs:
                logger.info("Step 6: Creating runs and results...")
                self._load_runs_and_results(runs, results)
            
            # Save updated mappings
            self._save_mappings()
            
            logger.info("Data import complete!")
            return {
                "status": "success",
                "stats": self.stats
            }
            
        except Exception as e:
            logger.error(f"Data import failed: {e}", exc_info=True)
            self.stats["errors"] += 1
            return {
                "status": "error",
                "error": str(e),
                "stats": self.stats
            }
    
    def _load_json(self, file_path: Path) -> Any:
        """Load JSON file."""
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _load_projects(self, projects: List[Dict[str, Any]]):
        """Load projects into Qase."""
        for project in tqdm(projects, desc="Creating projects"):
            try:
                result = self.qase_service.create_project(project)
                project_code = project.get("code")
                
                # Update mapping with Qase project code (should match, but verify)
                # Find the Xray project ID from mappings
                for xray_id, mapping in self.mappings.mappings.items():
                    if mapping.entity_type == "project" and mapping.qase_id == project_code:
                        # Mapping already exists, just verify
                        logger.debug(f"Project {project_code} created successfully")
                        break
                
                self.stats["projects"] += 1
                
            except Exception as e:
                logger.error(f"Error creating project {project.get('code')}: {e}")
                self.stats["errors"] += 1
    
    def _load_attachments(self, attachments_map: Dict[str, Dict[str, str]]):
        """Upload attachments and update mappings."""
        if not attachments_map:
            return
        
        # Group attachments by project (we need project code for upload)
        # For now, we'll need to determine project from mappings or use first project
        # This is a limitation - we need project code to upload attachments
        
        # Get first project code from mappings
        project_code = None
        for mapping in self.mappings.mappings.values():
            if mapping.entity_type == "project":
                project_code = mapping.qase_id
                break
        
        if not project_code:
            logger.warning("No project code found, skipping attachment upload")
            return
        
        for xray_id, att_data in tqdm(attachments_map.items(), desc="Uploading attachments"):
            try:
                local_path = att_data.get("local_path")
                if not local_path:
                    logger.warning(f"Attachment {xray_id} has no local_path, skipping")
                    continue
                
                # Handle different path formats
                # local_path might be "attachments\filename.png" or just "filename.png"
                if "\\" in local_path or "/" in local_path:
                    # Path contains directory separator
                    if local_path.startswith("attachments"):
                        # Relative path like "attachments\filename.png"
                        file_path = self.cache_manager.cache_dir / local_path.replace("\\", "/")
                    else:
                        # Absolute or relative path
                        file_path = Path(local_path)
                else:
                    # Just filename, look in attachments directory
                    file_path = self.cache_manager.cache_dir / "attachments" / local_path
                
                if not file_path.exists():
                    logger.warning(f"Attachment file not found: {file_path}")
                    continue
                
                logger.debug(f"Uploading attachment {xray_id}: {file_path} (exists: {file_path.exists()}, size: {file_path.stat().st_size} bytes)")
                result = self.qase_service.upload_attachment(project_code, file_path)
                
                # Update attachment mapping with Qase hash and URL
                att_data["hash"] = result.get("hash")
                att_data["url"] = result.get("url")
                
                self.stats["attachments"] += 1
                
            except Exception as e:
                logger.error(f"Error uploading attachment {xray_id}: {e}")
                self.stats["errors"] += 1
    
    def _update_cases_with_attachment_hashes(
        self,
        cases: Dict[str, List[Dict[str, Any]]],
        attachments_map: Dict[str, Dict[str, str]]
    ):
        """
        Update cases with attachment hashes after attachments are uploaded.
        
        Cases were transformed before attachments were uploaded, so they reference
        attachments by Xray ID. We need to replace those with Qase attachment hashes.
        """
        logger.info(f"Updating cases with attachment hashes. Attachments map has {len(attachments_map)} entries")
        logger.debug(f"Attachment map keys: {list(attachments_map.keys())[:5]}...")  # Show first 5 keys
        
        total_attachments_added = 0
        for project_code, case_list in cases.items():
            for case in case_list:
                updated_attachments = []
                case_title = case.get("title", "Unknown")
                
                # Start with any existing hashes (from inline attachments in description)
                current_attachments = case.get("attachments", [])
                for att_ref in current_attachments:
                    if isinstance(att_ref, str):
                        # Check if it's already a hash (long alphanumeric string)
                        if len(att_ref) > 20 and all(c.isalnum() or c in '-_' for c in att_ref):
                            # Looks like a hash, keep it
                            updated_attachments.append(att_ref)
                
                # Resolve Xray attachment IDs to Qase hashes
                xray_attachment_ids = case.get("_xray_attachment_ids", [])
                
                # Fallback: if _xray_attachment_ids is missing (old transformed data),
                # load from raw test case data
                if not xray_attachment_ids:
                    xray_issue_id = case.get("_xray_issue_id")
                    if xray_issue_id:
                        # Load raw test case to get attachment IDs
                        try:
                            raw_cases = self._load_json(
                                self.cache_manager.cache_dir / "raw" / "test_cases.json"
                            )
                            if raw_cases:
                                for raw_case in raw_cases:
                                    raw_jira = raw_case.get("jira", {})
                                    raw_issue_id = str(raw_jira.get("id", ""))
                                    if raw_issue_id == str(xray_issue_id):
                                        # Found matching case, extract attachment IDs
                                        raw_attachments = raw_jira.get("attachment", [])
                                        for att_ref in raw_attachments:
                                            if isinstance(att_ref, str):
                                                xray_attachment_ids.append(att_ref)
                                            elif isinstance(att_ref, dict):
                                                att_id = att_ref.get("id") or att_ref.get("attachmentId")
                                                if att_id:
                                                    xray_attachment_ids.append(str(att_id))
                                        break
                        except Exception as e:
                            logger.debug(f"Could not load raw test case for {xray_issue_id}: {e}")
                
                if xray_attachment_ids:
                    logger.debug(f"Case '{case_title}' has {len(xray_attachment_ids)} Xray attachment IDs: {xray_attachment_ids[:3]}...")
                
                for xray_id in xray_attachment_ids:
                    # Try multiple key formats
                    att_data = None
                    xray_id_str = str(xray_id)
                    
                    # Try exact match first
                    att_data = attachments_map.get(xray_id_str)
                    
                    # If not found, try other formats
                    if not att_data:
                        # Try without string conversion
                        att_data = attachments_map.get(xray_id)
                    
                    if not att_data:
                        # Try with different prefixes/suffixes
                        for prefix in ["", "attachment_", "att_"]:
                            for suffix in ["", "_attachment"]:
                                test_key = f"{prefix}{xray_id_str}{suffix}"
                                att_data = attachments_map.get(test_key)
                                if att_data:
                                    break
                            if att_data:
                                break
                    
                    if att_data and att_data.get("hash"):
                        updated_attachments.append(att_data["hash"])
                        total_attachments_added += 1
                        logger.debug(f"Resolved attachment {xray_id} -> hash {att_data['hash'][:10]}...")
                    else:
                        logger.warning(f"Attachment {xray_id} not found in map for case '{case_title}'. Available keys: {list(attachments_map.keys())[:10]}")
                
                # Update case with deduplicated attachments
                if updated_attachments:
                    case["attachments"] = list(set(updated_attachments))
                    logger.debug(f"Case '{case_title}' now has {len(case['attachments'])} attachments")
                else:
                    case["attachments"] = []
        
        logger.info(f"Added {total_attachments_added} attachment hashes to cases")
    
    def _load_suites(self, suites: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, int]]:
        """
        Load suites into Qase (hierarchical).
        
        Returns:
            Dictionary mapping project_code → {folder_path → suite_id}
        """
        suite_maps: Dict[str, Dict[str, int]] = {}
        
        for project_code, suite_list in suites.items():
            # Build parent mapping as we create suites
            path_to_suite_id: Dict[str, int] = {}
            suite_maps[project_code] = path_to_suite_id
            
            for suite in tqdm(suite_list, desc=f"Creating suites for {project_code}"):
                try:
                    # Handle parent relationship
                    suite_data = suite.copy()
                    parent_path = suite_data.pop("_parent_path", None)
                    if parent_path and parent_path in path_to_suite_id:
                        suite_data["parent_id"] = path_to_suite_id[parent_path]
                    else:
                        suite_data["parent_id"] = None
                    
                    result = self.qase_service.create_suite(project_code, suite_data)
                    suite_id = result.get("id")
                    
                    # Store suite ID for parent relationships and case matching
                    suite_desc = suite.get("description", "")
                    # Extract path from description: "Migrated from Xray folder: {path}"
                    if "Migrated from Xray folder:" in suite_desc:
                        path = suite_desc.split("Migrated from Xray folder:")[-1].strip()
                        path_to_suite_id[path] = suite_id
                    
                    self.stats["suites"] += 1
                    
                except Exception as e:
                    logger.error(f"Error creating suite {suite.get('title')}: {e}")
                    self.stats["errors"] += 1
        
        return suite_maps
    
    def _load_cases(self, cases: Dict[str, List[Dict[str, Any]]], suite_maps: Dict[str, Dict[str, int]]):
        """Load cases into Qase (bulk)."""
        for project_code, case_list in cases.items():
            # Update suite IDs in cases using the suite map from loaded suites
            suite_map = suite_maps.get(project_code, {})
            for case in case_list:
                folder_path = case.get("_folder_path")
                if folder_path and folder_path in suite_map:
                    case["suite_id"] = suite_map[folder_path]
                elif folder_path:
                    logger.debug(f"Case {case.get('title')} has folder path {folder_path} but no matching suite found")
            
            # Process in batches of 100 (Qase limit)
            batch_size = 100
            for i in tqdm(range(0, len(case_list), batch_size), desc=f"Creating cases for {project_code}"):
                batch = case_list[i:i + batch_size]
                
                # Clean up internal fields before sending
                clean_batch = []
                for case in batch:
                    clean_case = {k: v for k, v in case.items() if not k.startswith("_")}
                    clean_batch.append(clean_case)
                
                try:
                    result = self.qase_service.create_cases_bulk(project_code, clean_batch)
                    
                    # Update case ID mappings if IDs were preserved
                    created_cases = result.get("cases", [])
                    
                    # Even if response doesn't have cases, count them as created
                    # since the API call succeeded
                    self.stats["cases"] += len(clean_batch)
                    
                    # Try to map case IDs if we have them in response
                    if created_cases:
                        for j, created_case in enumerate(created_cases):
                            if j < len(batch):
                                original_case = batch[j]
                                xray_issue_id = original_case.get("_xray_issue_id")
                                qase_case_id = created_case.get("id")
                                
                                if xray_issue_id and qase_case_id:
                                    self.mappings.add_mapping(
                                        xray_id=str(xray_issue_id),
                                        qase_id=str(qase_case_id),
                                        entity_type="case"
                                    )
                    
                except Exception as e:
                    logger.error(f"Error creating cases batch: {e}")
                    self.stats["errors"] += 1
    
    def _load_runs_and_results(
        self,
        runs: List[Dict[str, Any]],
        results: List[Dict[str, Any]]
    ):
        """Load runs and results into Qase."""
        for run_data in tqdm(runs, desc="Creating runs"):
            try:
                project_code = run_data.get("_project_code")
                if not project_code:
                    continue
                
                # Resolve case IDs from Xray issue IDs
                case_ids = []
                for xray_case_id in run_data.get("cases", []):
                    qase_case_id = self.mappings.get_qase_id(str(xray_case_id))
                    if qase_case_id:
                        case_ids.append(int(qase_case_id))
                
                if not case_ids:
                    logger.warning(f"Run {run_data.get('title')} has no valid cases, skipping")
                    continue
                
                # Prepare run payload
                run_payload = {
                    "title": run_data.get("title"),
                    "description": run_data.get("description", ""),
                    "cases": case_ids
                }
                
                result = self.qase_service.create_run(project_code, run_payload)
                run_id = result.get("id")
                
                # Find and upload results for this run
                # Match results by test case ID (results have Xray case ID, need to map to Qase)
                run_results = []
                for r in results:
                    xray_case_id = str(r.get("testops_id", ""))
                    qase_case_id = self.mappings.get_qase_id(xray_case_id)
                    if qase_case_id and int(qase_case_id) in case_ids:
                        run_results.append(r)
                
                if run_results:
                    # Update result testops_id with actual Qase case IDs
                    clean_results = []
                    for result_data in run_results:
                        xray_case_id = str(result_data.get("testops_id", ""))
                        qase_case_id = self.mappings.get_qase_id(xray_case_id)
                        if qase_case_id:
                            clean_result = result_data.copy()
                            clean_result["testops_id"] = int(qase_case_id)
                            clean_results.append(clean_result)
                    
                    if clean_results:
                        # Process in batches of 500
                        batch_size = 500
                        for i in range(0, len(clean_results), batch_size):
                            batch = clean_results[i:i + batch_size]
                            try:
                                self.qase_service.create_results_bulk_v2(
                                    project_code,
                                    run_id,
                                    batch
                                )
                                self.stats["results"] += len(batch)
                            except Exception as e:
                                logger.error(f"Error creating results batch: {e}")
                                self.stats["errors"] += 1
                
                self.stats["runs"] += 1
                
            except Exception as e:
                logger.error(f"Error creating run {run_data.get('title')}: {e}")
                self.stats["errors"] += 1
    
    def _save_mappings(self):
        """Save updated mappings to cache."""
        mappings_dict = self.mappings.to_dict()
        self.cache_manager.save_mappings(mappings_dict)
        logger.info(f"Saved {len(mappings_dict)} ID mappings")
