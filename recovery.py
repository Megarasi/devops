"""
Recovery and automatic fallback engine for Intelligent Backup and Restoration System.
Implements candidate discovery, candidate ranking, integrity filtering, compatibility validation,
and automatic deterministic fallback (FR-09, FR-10, FR-11, FR-12, FR-13, FR-16, FR-17, FR-18, FR-19).
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
import itertools
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from intelligent_backup_system.compatibility import CompatibilityResult, DependencyManager
from intelligent_backup_system.logging_config import get_recovery_logger
from intelligent_backup_system.manifest_manager import ManifestEntry, ManifestManager
from intelligent_backup_system.restore import RestoreManager
from intelligent_backup_system.storage import StorageBackend
from intelligent_backup_system.validation import ValidationResult, ValidationRunner
from intelligent_backup_system.verify import VerificationResult, calculate_sha256, verify_backup_integrity


logger = get_recovery_logger()


@dataclass
class CandidateEvaluationRecord:
    """Detailed audit record of an evaluated candidate combination."""
    combination_id: str
    component_versions: Dict[str, str]
    manifest_entries: List[Dict[str, Any]]
    integrity_status: str               # "PASS" or "FAIL"
    integrity_details: List[Dict[str, Any]]
    compatibility_status: str           # "PASS", "FAIL", or "NOT_EVALUATED"
    compatibility_details: Dict[str, Any]
    validation_status: str              # "PASS", "FAIL", or "NOT_EVALUATED"
    validation_details: Dict[str, Any]
    decision: str                       # "SELECTED", "REJECTED_INTEGRITY", "REJECTED_COMPATIBILITY", "REJECTED_VALIDATION"
    rejection_reason: Optional[str] = None


@dataclass
class RecoveryExecutionRecord:
    """Complete machine-readable record of an entire recovery session (FR-13, FR-20)."""
    recovery_id: str
    started_at: str
    completed_at: str
    requested_components: List[str]
    candidates_considered_count: int
    evaluated_combinations: List[CandidateEvaluationRecord]
    selected_combination: Optional[CandidateEvaluationRecord]
    restored_files: List[str]
    isolated_staging_path: str
    promoted_to_working: bool
    overall_status: str                 # "SUCCESS", "PARTIAL", or "FAILED"
    unresolved_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RecoveryEngine:
    """Orchestrates candidate discovery, multi-version ranking, compatibility validation, and fallback."""

    def __init__(
        self,
        storage: StorageBackend,
        manifest_mgr: ManifestManager,
        dependency_mgr: DependencyManager,
        staging_dir: Union[str, Path],
        validation_runner: Optional[ValidationRunner] = None,
        max_combinations: int = 50
    ):
        self.storage = storage
        self.manifest_mgr = manifest_mgr
        self.dependency_mgr = dependency_mgr
        self.staging_dir = Path(staging_dir).resolve()
        self.validation_runner = validation_runner or ValidationRunner()
        self.max_combinations = max_combinations

    def discover_candidates_by_component(self, requested_components: List[str]) -> Dict[str, List[ManifestEntry]]:
        """
        Discovers all available backup candidates for each requested component from the manifest (FR-09).
        Candidates for each component are sorted newest first.
        """
        candidates: Dict[str, List[ManifestEntry]] = {}
        for comp in requested_components:
            entries = self.manifest_mgr.get_entries_for_component(comp)
            candidates[comp] = entries
            logger.info(f"Discovered {len(entries)} candidate versions for component '{comp}'.")
        return candidates

    def _verify_entry_integrity(self, entry: ManifestEntry) -> VerificationResult:
        """
        Verifies the cryptographic SHA-256 integrity of a stored backup object (FR-06, FR-10).
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "check.tmp"
            try:
                self.storage.download_file(entry.storage_key, temp_path)
                return verify_backup_integrity(
                    file_identifier=f"{entry.component_name}:{entry.component_version} ({entry.storage_key})",
                    actual_content_or_hash=temp_path,
                    expected_hash=entry.expected_sha256
                )
            except Exception as e:
                return VerificationResult(
                    file_identifier=entry.storage_key,
                    expected_hash=entry.expected_sha256,
                    actual_hash="",
                    passed=False,
                    reason=f"Failed to retrieve backup object from storage: {e}",
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

    def execute_recovery(
        self,
        requested_components: List[str],
        working_dir: Optional[Union[str, Path]] = None,
        promote: bool = False
    ) -> RecoveryExecutionRecord:
        """
        Executes the full intelligent recovery workflow with automatic fallback (FR-09 to FR-20).
        """
        recovery_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"=== Starting Recovery Session ID: {recovery_id} ===")
        logger.info(f"Requested components: {requested_components}")

        evaluated_combinations: List[CandidateEvaluationRecord] = []
        selected_record: Optional[CandidateEvaluationRecord] = None
        restored_files: List[str] = []
        unresolved_errors: List[str] = []

        # 1. Discover candidates for all requested components (FR-09)
        candidates_map = self.discover_candidates_by_component(requested_components)

        # Check if any component has zero backups
        for comp in requested_components:
            if not candidates_map.get(comp):
                msg = f"No backup versions found in manifest for requested component '{comp}'."
                logger.error(msg)
                unresolved_errors.append(msg)

        if unresolved_errors:
            completed_at = datetime.now(timezone.utc).isoformat()
            logger.error(f"Recovery ID={recovery_id} ABORTED: Missing required components.")
            return RecoveryExecutionRecord(
                recovery_id=recovery_id,
                started_at=started_at,
                completed_at=completed_at,
                requested_components=requested_components,
                candidates_considered_count=0,
                evaluated_combinations=[],
                selected_combination=None,
                restored_files=[],
                isolated_staging_path=str(self.staging_dir),
                promoted_to_working=False,
                overall_status="FAILED",
                unresolved_errors=unresolved_errors
            )

        # 2. Generate Cartesian product of candidate versions
        component_order = sorted(requested_components)
        candidate_lists = [candidates_map[c] for c in component_order]
        all_combinations = list(itertools.product(*candidate_lists))

        # Sort combinations deterministically: newest aggregate timestamps first (FR-17)
        def score_combination(combo: Tuple[ManifestEntry, ...]) -> Tuple[str, ...]:
            return tuple(entry.timestamp for entry in combo)

        all_combinations.sort(key=score_combination, reverse=True)
        logger.info(f"Generated {len(all_combinations)} possible recovery candidate combinations.")

        # 3. Evaluate candidate combinations deterministically
        restore_mgr = RestoreManager(storage=self.storage, staging_dir=self.staging_dir)

        for idx, combo in enumerate(all_combinations[:self.max_combinations]):
            combo_id = f"combo-{idx + 1}"
            comp_versions = {entry.component_name: entry.component_version for entry in combo}
            combo_entries_dict = [entry.to_dict() for entry in combo]

            logger.info(f"--- Evaluating {combo_id}: {comp_versions} ---")

            # 3a. Cryptographic Integrity Verification (FR-06, FR-10)
            combo_integrity_passed = True
            integrity_details: List[Dict[str, Any]] = []
            integrity_failure_reason = ""

            for entry in combo:
                res = self._verify_entry_integrity(entry)
                integrity_details.append(res.to_dict())
                if not res.passed:
                    combo_integrity_passed = False
                    integrity_failure_reason = f"Integrity failed for '{entry.component_name}' v{entry.component_version}: {res.reason}"
                    logger.warning(integrity_failure_reason)
                    break

            if not combo_integrity_passed:
                # Reject candidate and trigger fallback to next (FR-10, FR-11)
                eval_record = CandidateEvaluationRecord(
                    combination_id=combo_id,
                    component_versions=comp_versions,
                    manifest_entries=combo_entries_dict,
                    integrity_status="FAIL",
                    integrity_details=integrity_details,
                    compatibility_status="NOT_EVALUATED",
                    compatibility_details={},
                    validation_status="NOT_EVALUATED",
                    validation_details={},
                    decision="REJECTED_INTEGRITY",
                    rejection_reason=integrity_failure_reason
                )
                evaluated_combinations.append(eval_record)
                logger.info(f"Triggering automatic fallback from corrupted candidate set {combo_id} (FR-11).")
                continue

            # 3b. Compatibility Verification (FR-16)
            compat_res = self.dependency_mgr.validate_set(comp_versions)
            if not compat_res.compatible:
                # Reject combination due to dependency incompatibility (FR-16, Scenario C)
                rejection_msg = "; ".join(compat_res.violations)
                logger.warning(f"Compatibility violation on {combo_id}: {rejection_msg}")
                eval_record = CandidateEvaluationRecord(
                    combination_id=combo_id,
                    component_versions=comp_versions,
                    manifest_entries=combo_entries_dict,
                    integrity_status="PASS",
                    integrity_details=integrity_details,
                    compatibility_status="FAIL",
                    compatibility_details=compat_res.to_dict(),
                    validation_status="NOT_EVALUATED",
                    validation_details={},
                    decision="REJECTED_COMPATIBILITY",
                    rejection_reason=f"Cross-component rule violation: {rejection_msg}"
                )
                evaluated_combinations.append(eval_record)
                logger.info(f"Triggering automatic fallback from incompatible candidate set {combo_id} (FR-11, FR-17).")
                continue

            # 3c. Isolated Restoration & Post-Restoration Verification (FR-07, FR-08, FR-18)
            logger.info(f"Candidate set {combo_id} passed Integrity and Compatibility. Staging to isolated directory...")
            staged_paths, post_verify_results = restore_mgr.restore_candidate_set(list(combo))

            post_restore_all_passed = all(pv.passed for pv in post_verify_results)
            if not post_restore_all_passed:
                failed_post = [pv.reason for pv in post_verify_results if not pv.passed]
                eval_record = CandidateEvaluationRecord(
                    combination_id=combo_id,
                    component_versions=comp_versions,
                    manifest_entries=combo_entries_dict,
                    integrity_status="PASS",
                    integrity_details=integrity_details,
                    compatibility_status="PASS",
                    compatibility_details=compat_res.to_dict(),
                    validation_status="FAIL",
                    validation_details={"post_restore_verification_failures": failed_post},
                    decision="REJECTED_VALIDATION",
                    rejection_reason=f"Post-restoration checksum verification failed on disk: {'; '.join(failed_post)}"
                )
                evaluated_combinations.append(eval_record)
                continue

            # 3d. Post-Restoration Validation Smoke Tests (FR-19)
            val_res = self.validation_runner.run_validation(self.staging_dir)
            if not val_res.passed:
                val_fail_msg = "; ".join(val_res.failures)
                logger.warning(f"Application validation failed for {combo_id}: {val_fail_msg}")
                eval_record = CandidateEvaluationRecord(
                    combination_id=combo_id,
                    component_versions=comp_versions,
                    manifest_entries=combo_entries_dict,
                    integrity_status="PASS",
                    integrity_details=integrity_details,
                    compatibility_status="PASS",
                    compatibility_details=compat_res.to_dict(),
                    validation_status="FAIL",
                    validation_details=val_res.to_dict(),
                    decision="REJECTED_VALIDATION",
                    rejection_reason=f"Application smoke tests failed: {val_fail_msg}"
                )
                evaluated_combinations.append(eval_record)
                logger.info(f"Triggering automatic fallback from set failing smoke tests {combo_id} (FR-19).")
                continue

            # All checks PASSED! Candidate set selected!
            logger.info(f"Candidate set {combo_id} passed ALL CHECKS! Selecting as verified recovery set.")
            selected_record = CandidateEvaluationRecord(
                combination_id=combo_id,
                component_versions=comp_versions,
                manifest_entries=combo_entries_dict,
                integrity_status="PASS",
                integrity_details=integrity_details,
                compatibility_status="PASS",
                compatibility_details=compat_res.to_dict(),
                validation_status="PASS",
                validation_details=val_res.to_dict(),
                decision="SELECTED",
                rejection_reason=None
            )
            evaluated_combinations.append(selected_record)
            restored_files = [str(p) for p in staged_paths]
            break

        # 4. Handle Promotion if requested and successful (FR-18)
        promoted = False
        if selected_record and working_dir and promote:
            logger.info(f"Explicit promotion requested. Promoting verified files to '{working_dir}'...")
            restore_mgr.promote_to_working_directory(working_dir)
            promoted = True

        # 5. Final Status Determination
        if selected_record:
            overall_status = "SUCCESS"
            logger.info(f"Recovery ID={recovery_id} COMPLETED SUCCESSFULLY with set: {selected_record.component_versions}")
        else:
            overall_status = "FAILED"
            msg = "No valid, compatible backup candidate set could be verified (FR-12)."
            unresolved_errors.append(msg)
            logger.error(f"Recovery ID={recovery_id} FAILED: {msg}")

        completed_at = datetime.now(timezone.utc).isoformat()
        return RecoveryExecutionRecord(
            recovery_id=recovery_id,
            started_at=started_at,
            completed_at=completed_at,
            requested_components=requested_components,
            candidates_considered_count=len(evaluated_combinations),
            evaluated_combinations=evaluated_combinations,
            selected_combination=selected_record,
            restored_files=restored_files,
            isolated_staging_path=str(self.staging_dir),
            promoted_to_working=promoted,
            overall_status=overall_status,
            unresolved_errors=unresolved_errors
        )
