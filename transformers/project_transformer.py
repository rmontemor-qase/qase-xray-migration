"""Transformer for Xray projects to Qase projects."""

from typing import Dict, Any, List
from utils.cache_manager import CacheManager
from utils.logger import get_logger
from models.mappings import MappingStore
from transformers.xray_transformer import BaseTransformer

logger = get_logger(__name__)


class ProjectTransformer(BaseTransformer):
    """Transforms Xray projects to Qase projects."""
    
    def transform(
        self,
        projects_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Transform Xray projects to Qase projects.
        
        Args:
            projects_data: List of Xray project data
        
        Returns:
            List of Qase project payloads
        """
        qase_projects = []
        existing_codes = []
        
        for project in projects_data:
            try:
                project_name = project.get("name", project.get("key", "Unknown Project"))
                project_key = project.get("key", "")
                
                # Generate project code
                project_code = self.generate_project_code(project_name, existing_codes)
                existing_codes.append(project_code)
                
                qase_project = {
                    "title": project_name,
                    "code": project_code,
                    "description": f"Migrated from Xray project {project_key}",
                    "settings": {
                        "runs": {
                            "auto_complete": False
                        }
                    },
                    "access": "all"
                }
                
                qase_projects.append(qase_project)
                
                # Store mapping
                project_id = str(project.get("id", project_key))
                self.mappings.add_mapping(
                    xray_id=project_id,
                    qase_id=project_code,
                    entity_type="project",
                    metadata={"name": project_name, "key": project_key}
                )
                
                # Verify mapping was stored
                stored_qase_id = self.mappings.get_qase_id(project_id)
                self.logger.debug(f"Transformed project {project_key} (ID: {project_id}) → {project_code}, verified: {stored_qase_id}")
                
            except Exception as e:
                self.logger.error(f"Error transforming project {project.get('key')}: {e}")
                raise
        
        self.logger.info(f"Transformed {len(qase_projects)} projects")
        return qase_projects
