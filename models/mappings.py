"""ID mapping models for tracking Xray to Qase ID translations."""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass
class IDMapping:
    """Maps a single Xray ID to Qase ID."""
    xray_id: str
    qase_id: Optional[str] = None
    entity_type: str = "unknown"  # project, folder, test, execution, run, attachment
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MappingStore:
    """Stores all ID mappings for the migration."""
    mappings: Dict[str, IDMapping] = field(default_factory=dict)
    
    def add_mapping(self, xray_id: str, qase_id: Optional[str], entity_type: str, metadata: Optional[Dict] = None):
        """Add or update a mapping."""
        self.mappings[xray_id] = IDMapping(
            xray_id=xray_id,
            qase_id=qase_id,
            entity_type=entity_type,
            metadata=metadata or {}
        )
    
    def get_qase_id(self, xray_id: str) -> Optional[str]:
        """Get Qase ID for a given Xray ID."""
        mapping = self.mappings.get(xray_id)
        return mapping.qase_id if mapping else None
    
    def get_mapping(self, xray_id: str) -> Optional[IDMapping]:
        """Get full mapping for a given Xray ID."""
        return self.mappings.get(xray_id)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            xray_id: {
                "qase_id": mapping.qase_id,
                "entity_type": mapping.entity_type,
                "metadata": mapping.metadata
            }
            for xray_id, mapping in self.mappings.items()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MappingStore":
        """Create from dictionary (JSON deserialization)."""
        store = cls()
        for xray_id, mapping_data in data.items():
            store.mappings[xray_id] = IDMapping(
                xray_id=xray_id,
                qase_id=mapping_data.get("qase_id"),
                entity_type=mapping_data.get("entity_type", "unknown"),
                metadata=mapping_data.get("metadata", {})
            )
        return store
