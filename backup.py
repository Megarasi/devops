"""
Backup module for the Intelligent Backup and Restoration System.
Implements file selection, timestamping, SHA-256 computation, separate storage upload,
and manifest registration (FR-01, FR-02, FR-03, FR-04, FR-05).
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from intelligent_backup_system.logging_config import get_backup_logger
from intelligent_backup_system.manifest_manager import ManifestEntry, ManifestManager
from intelligent_backup_system.storage import StorageBackend
from intelligent_backup_system.verify import calculate_sha256


logger = get_backup_logger()


def generate_backup_id() -> str:
    """Generates a globally unique identifier for a backup session (FR-02)."""
    return str(uuid.uuid4())


def generate_timestamp() -> str:
    """Generates an ISO-8601 UTC timestamp (FR-02)."""
    return datetime.now(timezone.utc).isoformat()


def validate_and_sanitize_path(raw_path: Union[str, Path], base_dir: Optional[Path] = None) -> Path:
    """
    Validates a path, checks for existence and readability, and ensures no directory traversal (FR-01, NFR-02).
    """
    path = Path(raw_path)
    if not path.exists():
        raise FileNotFoundError(f"Selected path does not exist: '{raw_path}'")

    resolved = path.resolve()
    if base_dir:
        base_resolved = Path(base_dir).resolve()
        if not str(resolved).startswith(str(base_resolved)):
            raise ValueError(f"Path traversal detected: '{raw_path}' escapes base directory '{base_dir}'")

    return resolved


def select_files(paths: List[Union[str, Path]], base_dir: Optional[Path] = None) -> List[Path]:
    """
    Selects files or directories for backup, expanding directories recursively (FR-01).
    Handles missing or inaccessible files gracefully with descriptive exceptions.
    """
    selected: List[Path] = []
    for raw in paths:
        target = validate_and_sanitize_path(raw, base_dir=base_dir)
        if target.is_file():
            selected.append(target)
        elif target.is_dir():
            for root, _, files in os.walk(target):
                for f in files:
                    file_path = (Path(root) / f).resolve()
                    selected.append(file_path)
        else:
            logger.warning(f"Skipping special or unhandled path: {raw}")

    if not selected:
        raise ValueError("No valid files found in the specified paths.")

    return sorted(list(set(selected)))


def create_backup(
    paths: List[Union[str, Path]],
    component_name: str,
    component_version: str,
    storage: StorageBackend,
    manifest_mgr: ManifestManager,
    base_dir: Optional[Path] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> List[ManifestEntry]:
    """
    Orchestrates creating a timestamped, cryptographically verified backup (FR-01 to FR-05).

    Args:
        paths: List of file or directory paths to back up.
        component_name: Name of logical component (e.g. 'backend', 'database').
        component_version: Version identifier of the component (e.g. '2.0.0').
        storage: StorageBackend instance (Local or S3).
        manifest_mgr: ManifestManager instance for recording metadata.
        base_dir: Optional root path for calculating safe relative paths.
        metadata: Optional dictionary of additional context tags.

    Returns:
        List of created ManifestEntry instances.
    """
    backup_id = generate_backup_id()
    timestamp = generate_timestamp()
    meta = metadata or {}

    logger.info(f"Starting backup ID={backup_id} for component='{component_name}' version='{component_version}'")
    files_to_backup = select_files(paths, base_dir=base_dir)
    logger.info(f"Found {len(files_to_backup)} files to back up.")

    ref_dir = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    entries_created: List[ManifestEntry] = []

    for file_path in files_to_backup:
        # 1. Determine safe relative path
        try:
            rel_path = file_path.relative_to(ref_dir).as_posix()
        except ValueError:
            rel_path = file_path.name

        # 2. Calculate source SHA-256 using chunked streaming (FR-04)
        expected_sha256 = calculate_sha256(file_path)
        file_size = file_path.stat().st_size

        # 3. Define storage key: backups/{backup_id}/{rel_path}
        storage_key = f"backups/{backup_id}/{rel_path}"

        # 4. Upload / store in separate storage location (FR-03)
        storage.upload_file(file_path, storage_key)
        logger.info(f"Uploaded '{rel_path}' to '{storage_key}' (SHA-256: {expected_sha256[:12]}...)")

        # 5. Build and register manifest entry (FR-05)
        entry = ManifestEntry(
            backup_id=backup_id,
            timestamp=timestamp,
            component_name=component_name,
            component_version=component_version,
            relative_path=rel_path,
            storage_key=storage_key,
            expected_sha256=expected_sha256,
            file_size_bytes=file_size,
            metadata={
                **meta,
                "original_path": str(file_path),
                "created_at_utc": timestamp
            }
        )
        manifest_mgr.add_entry(entry)
        entries_created.append(entry)

    # 6. Save manifest atomically (FR-05)
    manifest_mgr.save_manifest()
    logger.info(f"Backup ID={backup_id} completed successfully. {len(entries_created)} entries registered in manifest.")

    return entries_created
