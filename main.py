"""
Command-Line Interface (CLI) for Intelligent Backup and Restoration System.
Team: CODE LOGGERS (DEVSPRINT2026)
Provides commands for backup, list-backups, verify, compatibility-check, recover, report, and health-check.
"""

import argparse
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path when invoked directly as a script
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from intelligent_backup_system.backup import create_backup
from intelligent_backup_system.compatibility import DependencyManager
from intelligent_backup_system.config_manager import ConfigManager
from intelligent_backup_system.logging_config import get_backup_logger, get_recovery_logger
from intelligent_backup_system.manifest_manager import ManifestManager
from intelligent_backup_system.recovery import RecoveryEngine
from intelligent_backup_system.report import ReportGenerator
from intelligent_backup_system.restore import RestoreManager
from intelligent_backup_system.storage import LocalStorageBackend, S3StorageBackend, StorageBackend
from intelligent_backup_system.validation import ValidationRunner
from intelligent_backup_system.verify import calculate_sha256, verify_backup_integrity


backup_logger = get_backup_logger()
recovery_logger = get_recovery_logger()


def get_storage_backend(config_mgr: ConfigManager, args: argparse.Namespace) -> StorageBackend:
    """Instantiates appropriate StorageBackend based on CLI args and configuration."""
    storage_mode = (args.storage or config_mgr.get("storage_mode", "local")).lower()

    if storage_mode == "s3":
        bucket = args.bucket or config_mgr.get("aws", {}).get("s3_bucket")
        region = args.region or config_mgr.get("aws", {}).get("region", "us-east-1")
        if not bucket:
            print("Error: S3 storage mode selected but no bucket specified. Provide --bucket or set AWS_S3_BUCKET.")
            sys.exit(1)
        return S3StorageBackend(bucket_name=bucket, region_name=region)
    else:
        local_path = args.storage_path or config_mgr.get("local_storage_path", "./storage_area")
        return LocalStorageBackend(base_dir=Path(local_path))


def cmd_backup(args: argparse.Namespace, config_mgr: ConfigManager) -> int:
    """Handles the 'backup' command."""
    storage = get_storage_backend(config_mgr, args)
    manifest_mgr = ManifestManager(storage=storage)

    try:
        entries = create_backup(
            paths=args.paths,
            component_name=args.component,
            component_version=args.version,
            storage=storage,
            manifest_mgr=manifest_mgr,
            base_dir=Path(args.base_dir) if args.base_dir else None
        )
        print(f"\n[SUCCESS] Backup completed successfully!")
        print(f"Component: {args.component} (version {args.version})")
        print(f"Backup ID: {entries[0].backup_id}")
        print(f"Files Backed Up: {len(entries)}")
        for e in entries:
            print(f"  - {e.relative_path} -> {e.storage_key} (SHA-256: {e.expected_sha256[:12]}...)")
        return 0
    except Exception as e:
        backup_logger.error(f"Backup failed: {e}")
        print(f"\n[FAILED] Backup operation failed: {e}")
        return 1


def cmd_list_backups(args: argparse.Namespace, config_mgr: ConfigManager) -> int:
    """Handles the 'list-backups' command."""
    storage = get_storage_backend(config_mgr, args)
    manifest_mgr = ManifestManager(storage=storage)
    entries = manifest_mgr.list_all_entries()

    if args.component:
        entries = [e for e in entries if e.component_name.lower() == args.component.lower()]

    if not entries:
        print("\nNo backup versions found in manifest.")
        return 0

    print(f"\n{'Backup ID':<38} {'Component':<12} {'Version':<10} {'Timestamp (UTC)':<24} {'Relative Path':<25}")
    print("-" * 115)
    for e in entries:
        print(f"{e.backup_id:<38} {e.component_name:<12} {e.component_version:<10} {e.timestamp:<24} {e.relative_path:<25}")
    print(f"\nTotal Backups: {len(entries)}")
    return 0


def cmd_verify(args: argparse.Namespace, config_mgr: ConfigManager) -> int:
    """Handles the 'verify' command."""
    storage = get_storage_backend(config_mgr, args)
    manifest_mgr = ManifestManager(storage=storage)

    entry = manifest_mgr.get_entry_by_id(args.backup_id)
    if not entry:
        print(f"[FAILED] Backup ID '{args.backup_id}' not found in manifest.")
        return 1

    print(f"Verifying backup object '{entry.storage_key}'...")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_file = Path(td) / "verify.tmp"
        try:
            storage.download_file(entry.storage_key, tmp_file)
            res = verify_backup_integrity(
                file_identifier=entry.storage_key,
                actual_content_or_hash=tmp_file,
                expected_hash=entry.expected_sha256
            )
            if res.passed:
                print(f"[PASS] Cryptographic Integrity Verified!")
                print(f"Expected SHA-256: {res.expected_hash}")
                print(f"Actual SHA-256:   {res.actual_hash}")
                return 0
            else:
                print(f"[FAIL] Cryptographic Integrity Failed!")
                print(f"Reason: {res.reason}")
                return 1
        except Exception as e:
            print(f"[FAIL] Verification error: {e}")
            return 1


def cmd_compatibility_check(args: argparse.Namespace, config_mgr: ConfigManager) -> int:
    """Handles the 'compatibility-check' command."""
    rules_path = args.rules or config_mgr.get("dependency_rules_path", "config/dependency_rules.json")
    dep_mgr = DependencyManager(rules_file=rules_path)

    # Parse components in format comp1=v1,comp2=v2
    comp_versions: Dict[str, str] = {}
    for pair in args.components:
        if "=" not in pair:
            print(f"Error: Component specification '{pair}' must be formatted as 'component=version' (e.g. backend=2.0.0).")
            return 1
        c, v = pair.split("=", 1)
        comp_versions[c.strip()] = v.strip()

    res = dep_mgr.validate_set(comp_versions)
    print("\n=== Compatibility Validation Result ===")
    print(f"Evaluated Set: {comp_versions}")
    print(f"Rules Checked: {res.rules_checked}")
    if res.compatible:
        print(f"[PASS] COMPATIBLE: {res.reason}")
        return 0
    else:
        print(f"[FAIL] INCOMPATIBLE: {res.reason}")
        for v in res.violations:
            print(f"  - {v}")
        return 1


def cmd_recover(args: argparse.Namespace, config_mgr: ConfigManager) -> int:
    """Handles the 'recover' command with automatic fallback and evidence reporting."""
    storage = get_storage_backend(config_mgr, args)
    manifest_mgr = ManifestManager(storage=storage)
    rules_path = args.rules or config_mgr.get("dependency_rules_path", "config/dependency_rules.json")
    dep_mgr = DependencyManager(rules_file=rules_path)

    staging_dir = args.staging or config_mgr.get("isolated_staging_path", "./staging_area")
    validation_runner = ValidationRunner(custom_command=args.validation_command)

    engine = RecoveryEngine(
        storage=storage,
        manifest_mgr=manifest_mgr,
        dependency_mgr=dep_mgr,
        staging_dir=staging_dir,
        validation_runner=validation_runner
    )

    requested = [c.strip() for c in args.components.split(",") if c.strip()]
    record = engine.execute_recovery(
        requested_components=requested,
        working_dir=args.working_dir,
        promote=args.promote
    )

    report_gen = ReportGenerator(storage=storage, reports_dir=args.reports_dir or "reports")
    json_path, md_path = report_gen.save_reports(record)

    print("\n" + "=" * 60)
    print(f"RECOVERY SUMMARY: {record.overall_status}")
    print("=" * 60)
    print(f"Recovery ID:        {record.recovery_id}")
    print(f"Status:             {record.overall_status}")
    print(f"Isolated Staging:   {record.isolated_staging_path}")
    if record.selected_combination:
        print(f"Selected Set:       {record.selected_combination.component_versions}")
    print(f"Audit Reports:      {json_path} & {md_path}")
    print("=" * 60 + "\n")

    return 0 if record.overall_status == "SUCCESS" else 1


def cmd_report(args: argparse.Namespace, config_mgr: ConfigManager) -> int:
    """Displays a generated report."""
    rec_id = args.recovery_id
    report_file = Path(args.reports_dir or "reports") / rec_id / "report.md"
    if not report_file.is_file():
        print(f"Report file not found at: {report_file}")
        return 1
    print(report_file.read_text(encoding="utf-8"))
    return 0


def cmd_health_check(args: argparse.Namespace, config_mgr: ConfigManager) -> int:
    """Performs health check on configuration, storage, and dependencies."""
    print("=== System Health Check ===")
    print(f"Storage Mode:         {config_mgr.get('storage_mode')}")
    print(f"Local Storage Path:   {config_mgr.get('local_storage_path')}")
    print(f"Isolated Staging:     {config_mgr.get('isolated_staging_path')}")
    print(f"Dependency Rules:     {config_mgr.get('dependency_rules_path')}")
    print(f"S3 Bucket:            {config_mgr.get('aws', {}).get('s3_bucket') or '(not set)'}")

    # Check dependency rules exist
    rules_file = Path(config_mgr.get("dependency_rules_path", "config/dependency_rules.json"))
    if rules_file.exists():
        print("[OK] Dependency rules configuration file exists.")
    else:
        print("[WARN] Dependency rules file not found.")

    storage = get_storage_backend(config_mgr, args)
    try:
        keys = storage.list_objects()
        print(f"[OK] Storage backend accessible. Current objects in storage: {len(keys)}")
    except Exception as e:
        print(f"[FAIL] Storage accessibility check failed: {e}")
        return 1

    print("[SUCCESS] All system health checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Builds and returns the top-level argument parser."""
    parser = argparse.ArgumentParser(
        description="Intelligent Backup and Restoration System with Dependency Validation (DEVSPRINT2026 - CODE LOGGERS)"
    )
    parser.add_argument("--config", help="Path to custom config JSON file.")
    parser.add_argument("--storage", choices=["local", "s3"], help="Storage backend mode (default: local).")
    parser.add_argument("--storage-path", help="Path for local storage mode (default: ./storage_area).")
    parser.add_argument("--bucket", help="AWS S3 bucket name (for s3 storage mode).")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1).")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # backup
    p_backup = subparsers.add_parser("backup", help="Create a timestamped backup of selected files or directories.")
    p_backup.add_argument("--paths", nargs="+", required=True, help="One or more file or directory paths to back up.")
    p_backup.add_argument("--component", required=True, help="Component name (e.g. backend, database).")
    p_backup.add_argument("--version", required=True, help="Component version (e.g. 1.0.0, 2.0.0).")
    p_backup.add_argument("--base-dir", help="Base directory for relative path calculation.")

    # list-backups
    p_list = subparsers.add_parser("list-backups", help="List registered backups in manifest.")
    p_list.add_argument("--component", help="Filter by component name.")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify cryptographic SHA-256 integrity of a backup object.")
    p_verify.add_argument("--backup-id", required=True, help="Backup ID to verify.")

    # compatibility-check
    p_compat = subparsers.add_parser("compatibility-check", help="Check compatibility for component versions.")
    p_compat.add_argument("--components", nargs="+", required=True, help="Component version pairs: comp1=v1 comp2=v2")
    p_compat.add_argument("--rules", help="Path to custom dependency rules file.")

    # recover
    p_recover = subparsers.add_parser("recover", help="Run intelligent recovery with automatic fallback.")
    p_recover.add_argument("--components", required=True, help="Comma-separated list of components (e.g. backend,database).")
    p_recover.add_argument("--staging", help="Isolated staging directory for restoration.")
    p_recover.add_argument("--working-dir", help="Live working directory (for promotion).")
    p_recover.add_argument("--promote", action="store_true", help="Explicitly promote verified files to working directory.")
    p_recover.add_argument("--rules", help="Path to dependency rules file.")
    p_recover.add_argument("--reports-dir", help="Directory to save recovery evidence reports.")
    p_recover.add_argument("--validation-command", help="Custom command to run in staging directory for smoke testing.")

    # report
    p_report = subparsers.add_parser("report", help="View a recovery evidence report.")
    p_report.add_argument("--recovery-id", required=True, help="Recovery ID.")
    p_report.add_argument("--reports-dir", help="Reports root directory.")

    # health-check
    subparsers.add_parser("health-check", help="Run system sanity checks.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    config_mgr = ConfigManager(config_file=args.config)
    config_mgr.validate()

    dispatch = {
        "backup": cmd_backup,
        "list-backups": cmd_list_backups,
        "verify": cmd_verify,
        "compatibility-check": cmd_compatibility_check,
        "recover": cmd_recover,
        "report": cmd_report,
        "health-check": cmd_health_check
    }

    handler = dispatch.get(args.command)
    if handler:
        sys.exit(handler(args, config_mgr))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
