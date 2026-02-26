"""Transformer for Xray Cloud data to Qase format."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
import re
import json
from pathlib import Path

from utils.cache_manager import CacheManager
from utils.logger import get_logger
from models.mappings import MappingStore

logger = get_logger(__name__)


class BaseTransformer(ABC):
    """Base class for transformers with common utilities."""
    
    def __init__(self, cache_manager: CacheManager, mappings: Optional[MappingStore] = None):
        """
        Initialize transformer with cache manager.
        
        Args:
            cache_manager: CacheManager instance for reading extracted data
            mappings: Optional MappingStore for tracking ID mappings
        """
        self.cache_manager = cache_manager
        self.mappings = mappings or MappingStore()
        self.logger = get_logger(self.__class__.__name__)
    
    @abstractmethod
    def transform(self) -> Dict[str, Any]:
        """
        Transform extracted data to target format.
        
        Returns:
            Dictionary with transformation statistics and metadata
        """
        pass
    
    def convert_jira_doc_to_markdown(self, doc: Dict[str, Any]) -> str:
        """
        Convert Jira document format (Atlassian Document Format) to Markdown.
        
        Args:
            doc: Jira document object with type, version, content
        
        Returns:
            Markdown string
        """
        if not doc or not isinstance(doc, dict):
            return ""
        
        content = doc.get("content", [])
        if not content:
            return ""
        
        return self._process_content_nodes(content)
    
    def _process_content_nodes(self, nodes: List[Dict[str, Any]]) -> str:
        """Process content nodes recursively."""
        result = []
        
        for node in nodes:
            node_type = node.get("type", "")
            content = node.get("content", [])
            text = node.get("text", "")
            marks = node.get("marks", [])
            
            # Apply marks (bold, italic, code, etc.)
            formatted_text = text
            for mark in marks:
                mark_type = mark.get("type", "")
                if mark_type == "strong":
                    formatted_text = f"**{formatted_text}**"
                elif mark_type == "em":
                    formatted_text = f"*{formatted_text}*"
                elif mark_type == "code":
                    formatted_text = f"`{formatted_text}`"
                elif mark_type == "link":
                    href = mark.get("attrs", {}).get("href", "")
                    formatted_text = f"[{formatted_text}]({href})"
            
            if node_type == "paragraph":
                para_text = formatted_text + self._process_content_nodes(content)
                if para_text.strip():
                    result.append(para_text)
            elif node_type == "heading":
                level = node.get("attrs", {}).get("level", 1)
                heading_text = formatted_text + self._process_content_nodes(content)
                if heading_text.strip():
                    result.append(f"{'#' * level} {heading_text}")
            elif node_type == "bulletList":
                list_items = self._process_content_nodes(content)
                result.append(list_items)
            elif node_type == "orderedList":
                list_items = self._process_content_nodes(content)
                result.append(list_items)
            elif node_type == "listItem":
                item_text = formatted_text + self._process_content_nodes(content)
                if item_text.strip():
                    result.append(f"- {item_text}")
            elif node_type == "codeBlock":
                code = node.get("content", [{}])[0].get("text", "") if node.get("content") else ""
                language = node.get("attrs", {}).get("language", "")
                result.append(f"```{language}\n{code}\n```")
            elif node_type == "hardBreak":
                result.append("\n")
            elif node_type == "media":
                # Handle media nodes (images, videos, etc.)
                attrs = node.get("attrs", {})
                media_type = attrs.get("type", "")
                url = attrs.get("url", "")
                alt = attrs.get("alt", "")
                
                if media_type == "file" or url:
                    if alt:
                        result.append(f"![{alt}]({url})")
                    else:
                        result.append(f"![]({url})")
            elif node_type == "text":
                if formatted_text:
                    result.append(formatted_text)
            else:
                # For unknown types, process content recursively
                if content:
                    result.append(self._process_content_nodes(content))
        
        return "\n".join(result)
    
    def extract_attachment_ids_from_text(self, text: str) -> List[str]:
        """
        Extract attachment IDs from text (Jira format).
        
        Args:
            text: Text that may contain attachment references
        
        Returns:
            List of attachment IDs found
        """
        if not text:
            return []
        
        # Pattern for Jira attachment references
        # Could be in various formats like [^image.png] or direct references
        # For now, we'll look for common patterns
        attachment_ids = []
        
        # Pattern: [^filename.ext] - Jira attachment reference
        pattern = r'\[\^([^\]]+)\]'
        matches = re.findall(pattern, text)
        attachment_ids.extend(matches)
        
        return attachment_ids
    
    def replace_attachment_references(
        self,
        text: str,
        attachment_map: Dict[str, Dict[str, str]]
    ) -> Tuple[str, List[str]]:
        """
        Replace attachment references in text with Qase markdown links.
        
        Args:
            text: Text containing attachment references
            attachment_map: Map of Xray attachment ID → Qase attachment object
        
        Returns:
            Tuple of (processed_text, list_of_attachment_hashes)
        """
        if not text:
            return "", []
        
        processed_text = text
        attachment_hashes = []
        
        # Find all attachment references and replace them
        # This is a simplified version - may need to be enhanced based on actual Xray format
        # For now, we'll handle common patterns
        
        # Pattern: [^filename.ext] - replace with markdown image/link
        def replace_attachment(match):
            filename = match.group(1)
            # Try to find attachment by filename in map
            for att_id, att_data in attachment_map.items():
                if att_data.get("filename") == filename:
                    hash_val = att_data.get("hash")
                    url = att_data.get("url")
                    if hash_val and url:
                        attachment_hashes.append(hash_val)
                        # Determine if it's an image based on extension
                        if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
                            return f"![{filename}]({url})"
                        else:
                            return f"[{filename}]({url})"
            return match.group(0)  # Keep original if not found
        
        pattern = r'\[\^([^\]]+)\]'
        processed_text = re.sub(pattern, replace_attachment, processed_text)
        
        return processed_text, list(set(attachment_hashes))  # Remove duplicates
    
    def generate_project_code(self, project_name: str, existing_codes: List[str]) -> str:
        """
        Generate a short project code from project name.
        
        Args:
            project_name: Full project name
            existing_codes: List of already used codes
        
        Returns:
            Short code (max 10 characters)
        """
        # Extract first letters of words
        words = re.findall(r'\b\w', project_name)
        code = ''.join(words).upper()
        
        # Remove non-alphabetic characters and truncate to 10
        code = re.sub(r'[^A-Z]', '', code)[:10]
        
        # Ensure minimum length
        if len(code) < 2:
            code = project_name[:10].upper()
            code = re.sub(r'[^A-Z0-9]', '', code)
        
        # Handle duplicates
        base_code = code
        counter = 0
        while code in existing_codes:
            counter += 1
            if counter > 26:
                # Fallback: use first 10 chars of name
                code = re.sub(r'[^A-Z0-9]', '', project_name.upper())[:10]
                break
            code = base_code[:9] + chr(ord('A') + counter - 1)
        
        return code


class XrayTransformer(BaseTransformer):
    """
    Main transformer orchestrator for Xray Cloud data to Qase format.
    
    Coordinates specialized transformers for each entity type:
    - Projects → Qase projects
    - Folders → Qase suites (hierarchical)
    - Test Cases → Qase cases
    - Attachments → Qase attachments (mapping)
    - Test Executions → Qase runs
    - Test Runs → Qase results
    """
    
    def __init__(self, cache_manager: CacheManager, mappings: Optional[MappingStore] = None):
        """Initialize Xray transformer and specialized transformers."""
        # Ensure we have a shared mappings instance for all transformers
        shared_mappings = mappings or MappingStore()
        super().__init__(cache_manager, shared_mappings)
        
        # Lazy import to avoid circular dependency
        from transformers.project_transformer import ProjectTransformer
        from transformers.suite_transformer import SuiteTransformer
        from transformers.attachment_transformer import AttachmentTransformer
        from transformers.case_transformer import CaseTransformer
        from transformers.run_transformer import RunTransformer
        
        # Initialize specialized transformers with the same shared mappings instance
        self.project_transformer = ProjectTransformer(cache_manager, shared_mappings)
        self.suite_transformer = SuiteTransformer(cache_manager, shared_mappings)
        self.attachment_transformer = AttachmentTransformer(cache_manager, shared_mappings)
        self.case_transformer = CaseTransformer(cache_manager, shared_mappings)
        self.run_transformer = RunTransformer(cache_manager, shared_mappings)
        
        self.transformed_data = {}
        self.stats = {
            "projects": 0,
            "suites": 0,
            "cases": 0,
            "runs": 0,
            "results": 0,
            "attachments_mapped": 0,
            "errors": 0
        }
    
    def transform(self) -> Dict[str, Any]:
        """
        Transform all extracted Xray data to Qase format.
        
        Returns:
            Dictionary with transformation statistics
        """
        self.logger.info("Starting Xray to Qase transformation...")
        
        try:
            # Load raw data
            projects_data = self.cache_manager.load_raw_data("projects")
            folders_data = self.cache_manager.load_raw_data("folders")
            test_cases_data = self.cache_manager.load_raw_data("test_cases")
            attachments_data = self.cache_manager.load_raw_data("attachments")
            
            if not projects_data:
                raise ValueError("No projects data found in cache")
            if not test_cases_data:
                raise ValueError("No test cases data found in cache")
            
            # Transform in order
            self.logger.info("Step 1: Transforming projects...")
            qase_projects = self.project_transformer.transform(projects_data)
            self.stats["projects"] = len(qase_projects)
            
            # Debug: Check mappings after project transformation
            self.logger.debug(f"Mappings after projects: {list(self.mappings.mappings.keys())}")
            
            self.logger.info("Step 2: Transforming folders to suites...")
            qase_suites = self.suite_transformer.transform(folders_data, projects_data)
            self.stats["suites"] = sum(len(suites) for suites in qase_suites.values())
            
            self.logger.info("Step 3: Mapping attachments...")
            qase_attachments_map = self.attachment_transformer.transform(attachments_data or [])
            self.stats["attachments_mapped"] = len(qase_attachments_map)
            
            self.logger.info("Step 4: Transforming test cases...")
            # Debug: Check what project IDs we're looking for
            unique_project_ids = set(str(tc.get("projectId", "")) for tc in test_cases_data[:5])
            self.logger.debug(f"Sample project IDs from test cases: {unique_project_ids}")
            self.logger.debug(f"Available mappings: {list(self.mappings.mappings.keys())}")
            
            qase_cases = self.case_transformer.transform(
                test_cases_data,
                qase_suites,
                qase_attachments_map
            )
            self.stats["cases"] = sum(len(cases) for cases in qase_cases.values())
            
            # Check if test executions exist
            try:
                executions_data = self.cache_manager.load_raw_data("test_executions")
                if executions_data:
                    self.logger.info("Step 5: Transforming test executions and runs...")
                    qase_runs, qase_results = self.run_transformer.transform(
                        executions_data,
                        qase_cases
                    )
                    self.stats["runs"] = len(qase_runs)
                    self.stats["results"] = len(qase_results)
                    self.transformed_data["runs"] = qase_runs
                    self.transformed_data["results"] = qase_results
                else:
                    self.logger.info("No test executions found, skipping runs/results transformation")
            except FileNotFoundError:
                self.logger.info("No test executions found, skipping runs/results transformation")
            
            # Store transformed data
            self.transformed_data["projects"] = qase_projects
            self.transformed_data["suites"] = qase_suites
            self.transformed_data["cases"] = qase_cases
            self.transformed_data["attachments_map"] = qase_attachments_map
            
            # Save transformed data
            self._save_transformed_data()
            
            # Save mappings
            self._save_mappings()
            
            self.logger.info("Transformation complete!")
            return {
                "status": "success",
                "stats": self.stats,
                "transformed_data": {
                    "projects": len(qase_projects),
                    "suites": self.stats["suites"],
                    "cases": self.stats["cases"],
                    "runs": len(self.transformed_data.get("runs", [])),
                    "results": len(self.transformed_data.get("results", []))
                }
            }
            
        except Exception as e:
            self.logger.error(f"Transformation failed: {e}", exc_info=True)
            self.stats["errors"] += 1
            return {
                "status": "error",
                "error": str(e),
                "stats": self.stats
            }
    
    def _save_transformed_data(self):
        """Save transformed data to cache."""
        transformed_dir = self.cache_manager.cache_dir / "transformed"
        transformed_dir.mkdir(exist_ok=True)
        
        # Save each entity type
        for entity_type, data in self.transformed_data.items():
            file_path = transformed_dir / f"{entity_type}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        
        self.logger.info(f"Saved transformed data to {transformed_dir}")
    
    def _save_mappings(self):
        """Save ID mappings to cache."""
        mappings_dict = self.mappings.to_dict()
        self.cache_manager.save_mappings(mappings_dict)
        self.logger.info(f"Saved {len(mappings_dict)} ID mappings")
