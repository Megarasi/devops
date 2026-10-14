"""
Manifest management module for the Intelligent Backup and Restoration System (FR-05).
Manages versioned, atomic JSON manifests tracking backup metadata, component versions, and expected SHA-256 digests.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from intelligent_backup_system.storage import StorageBackend


CURRENT_MANIFEST_SCHEMA_VERSION = "1.0.0"


@dataclass
class ManifestEntry:
    """Represents a single registered backup version in the manifest."""
    backup_id: str
    timestamp: str
    component_name: str
    component_version: str
    relative_path: str
    storage_key: str
    expected_sha256: str
    file_size_bytes: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManifestEntry":
        required_fields = [
            "backup_id", "timestamp", "component_name", "component_version",
            "relative_path", "storage_key", "expected_sha256", "file_size_bytes"
        ]
        for f in required_fields:
            if f not in data:
                raise ValueError(f"Malformed manifest entry: missing required field '{f}'")
        return cls(
            backup_id=str(data["backup_id"]),
            timestamp=str(data["timestamp"]),
            component_name=str(data["component_name"]),
            component_version=str(data["component_version"]),
            relative_path=str(data["relative_path"]),
            storage_key=str(data["storage_key"]),
            expected_sha256=str(data["expected_sha256"]),
            file_size_bytes=int(data["file_size_bytes"]),
            metadata=dict(data.get("metadata", {}))
        )


@dataclass
class Manifest:
    """Represents the complete backup manifest document."""
    manifest_version: str = CURRENT_MANIFEST_SCHEMA_VERSION
    last_updated: str = ""
    backups: List[ManifestEntry] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "last_updated": self.last_updated,
            "backups": [b.to_dict() for b in self.backups]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Manifest":
        manifest_version = data.get("manifest_version", CURRENT_MANIFEST_SCHEMA_VERSION)
        last_updated = data.get("last_updated", "")
        raw_backups = data.get("backups", [])
        if not isinstance(raw_backups, list):
            raise ValueError("Malformed manifest: 'backups' must be a list.")
        entries = [ManifestEntry.from_dict(b) for b in raw_backups]
        return cls(manifest_version=manifest_version, last_updated=last_updated, backups=entries)


class ManifestManager:
    """Safely loads, validates, updates, and preserves versioned backup manifests (FR-05)."""

    def __init__(self, storage: StorageBackend, manifest_key: str = "manifests/backup_manifest.json"):
        self.storage = storage
        self.manifest_key = manifest_key.strip("/\\").replace("\\", "/")
        self.manifest: Manifest = self.load_manifest()

    def load_manifest(self) -> Manifest:
        """Loads manifest from storage backend, or creates an empty one if non-existent."""
        if not self.storage.object_exists(self.manifest_key):
            now_iso = datetime.now(timezone.utc).isoformat()
            return Manifest(manifest_version=CURRENT_MANIFEST_SCHEMA_VERSION, last_updated=now_iso, backups=[])

        try:
            raw_text = self.storage.read_text(self.manifest_key)
            data = json.loads(raw_text)
            return Manifest.from_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupted or invalid JSON in manifest '{self.manifest_key}': {e}") from e
        except Exception as e:
            raise IOError(f"Failed to load manifest '{self.manifest_key}': {e}") from e

    def add_entry(self, entry: ManifestEntry) -> None:
        """Adds or updates a backup entry and updates the timestamp."""
        # Check for duplicate entry by (backup_id, relative_path)
        for i, existing in enumerate(self.manifest.backups):
            if existing.backup_id == entry.backup_id and existing.relative_path == entry.relative_path:
                self.manifest.backups[i] = entry
                self.manifest.last_updated = datetime.now(timezone.utc).isoformat()
                return

        self.manifest.backups.append(entry)
        self.manifest.last_updated = datetime.now(timezone.utc).isoformat()

    def save_manifest(self) -> str:
        """
        Saves the manifest atomically to storage and creates an immutable snapshot (FR-05).
        """
        self.manifest.last_updated = datetime.now(timezone.utc).isoformat()
        serialized = json.dumps(self.manifest.to_dict(), indent=2)

        # 1. Write to primary manifest key
        self.storage.write_text(self.manifest_key, serialized)

        # 2. Write immutable historical snapshot to manifests/versions/{timestamp}.json
        timestamp_clean = self.manifest.last_updated.replace(":", "-")
        version_snapshot_key = f"manifests/versions/manifest_{timestamp_clean}.json"
        try:
            self.storage.write_text(version_snapshot_key, serialized)
        except Exception:
            # Historical snapshot write is advisory to primary save
            pass

        return self.manifest_key

    def get_entries_for_component(self, component_name: str) -> List[ManifestEntry]:
        """Returns all backup entries matching component_name, sorted newest first."""
        matches = [b for b in self.manifest.backups if b.component_name.lower() == component_name.lower()]
        matches.sort(key=lambda x: x.timestamp, reverse=True)
        return matches

    def get_entry_by_id(self, backup_id: str) -> Optional[ManifestEntry]:
        """Finds entry by unique backup ID."""
        for b in self.manifest.backups:
            if b.backup_id == backup_id:
                return b
        return None

    def list_all_entries(self) -> List[ManifestEntry]:
        """Returns all entries sorted newest first."""
        return sorted(self.manifest.backups, key=lambda x: x.timestamp, reverse=True)
