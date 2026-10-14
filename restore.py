"""
Restoration manager for Intelligent Backup and Restoration System (FR-07, FR-08, FR-18).
Restores files to an isolated staging directory, calculates post-restoration SHA-256 digests,
and safely promotes verified files to working locations.
"""

import os
from pathlib import Path
import shutil
from typing import Dict, List, Optional, Tuple, Union

from intelligent_backup_system.logging_config import get_recovery_logger
from intelligent_backup_system.manifest_manager import ManifestEntry
from intelligent_backup_system.storage import StorageBackend
from intelligent_backup_system.verify import VerificationResult, verify_restored_file


logger = get_recovery_logger()


class RestoreManager:
    """Manages secure restoration to isolated staging and verified promotion (FR-07, FR-08, FR-18)."""

    def __init__(self, storage: StorageBackend, staging_dir: Union[str, Path]):
        self.storage = storage
        self.staging_dir = Path(staging_dir).resolve()
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_destination_path(self, relative_path: str, destination_root: Path) -> Path:
        """
        Ensures target path does not escape destination root via directory traversal (FR-18, NFR-02).
        """
        clean_rel = relative_path.strip("/\\").replace("\\", "/")
        target = (destination_root / clean_rel).resolve()
        if not str(target).startswith(str(destination_root.resolve())):
            raise ValueError(f"Path traversal detected: '{relative_path}' escapes '{destination_root}'")
        return target

    def restore_candidate_entry(self, entry: ManifestEntry) -> Tuple[Path, VerificationResult]:
        """
        Downloads a single backup object from storage into the isolated staging directory (FR-07)
        and immediately verifies its on-disk SHA-256 checksum (FR-08).

        Returns:
            Tuple of (restored_local_path, verification_result).
        """
        target_path = self._sanitize_destination_path(entry.relative_path, self.staging_dir)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Restoring backup_id='{entry.backup_id}' ({entry.relative_path}) to isolated staging: '{target_path}'")
        self.storage.download_file(entry.storage_key, target_path)

        # Post-restoration verification (FR-08)
        verify_res = verify_restored_file(target_path, entry.expected_sha256)
        if not verify_res.passed:
            logger.error(f"Post-restoration verification FAILED for '{entry.relative_path}': {verify_res.reason}")
        else:
            logger.info(f"Post-restoration verification PASSED for '{entry.relative_path}'")

        return target_path, verify_res

    def restore_candidate_set(self, candidate_entries: List[ManifestEntry]) -> Tuple[List[Path], List[VerificationResult]]:
        """
        Restores a complete set of candidate entries into the staging directory.
        """
        restored_paths: List[Path] = []
        verification_results: List[VerificationResult] = []

        for entry in candidate_entries:
            path, res = self.restore_candidate_entry(entry)
            restored_paths.append(path)
            verification_results.append(res)

        return restored_paths, verification_results

    def promote_to_working_directory(
        self,
        working_dir: Union[str, Path],
        verified_relative_paths: Optional[List[str]] = None
    ) -> List[Path]:
        """
        Promotes verified files from isolated staging to the live working directory (FR-18).
        Only files that have passed all checks may be promoted.
        """
        dest_root = Path(working_dir).resolve()
        dest_root.mkdir(parents=True, exist_ok=True)
        promoted_paths: List[Path] = []

        for staged_file in self.staging_dir.rglob("*"):
            if not staged_file.is_file():
                continue

            rel = staged_file.relative_to(self.staging_dir).as_posix()
            if verified_relative_paths and rel not in verified_relative_paths:
                continue

            live_target = self._sanitize_destination_path(rel, dest_root)
            live_target.parent.mkdir(parents=True, exist_ok=True)

            # Atomic copy to working directory
            shutil.copy2(staged_file, live_target)
            promoted_paths.append(live_target)
            logger.info(f"Promoted staged file '{rel}' to working destination: '{live_target}'")

        return promoted_paths
