"""
Configuration manager for the Intelligent Backup and Restoration System.
Loads, validates, and merges default and user-supplied configuration.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "storage_mode": "local",
    "local_storage_path": "./storage_area",
    "isolated_staging_path": "./staging_area",
    "manifest_path": "manifests/backup_manifest.json",
    "dependency_rules_path": "config/dependency_rules.json",
    "aws": {
        "s3_bucket": "",
        "region": "us-east-1",
        "prefix_backups": "backups/",
        "prefix_manifests": "manifests/",
        "prefix_reports": "reports/",
        "prefix_logs": "logs/"
    },
    "search_limits": {
        "max_candidate_evaluations": 50,
        "max_combinations_tested": 100
    },
    "logging": {
        "level": "INFO",
        "backup_log": "logs/backup.log",
        "recovery_log": "logs/recovery.log"
    }
}


class ConfigManager:
    """Manages application configuration with validation and environment overrides."""

    def __init__(self, config_file: Optional[str] = None):
        self.config: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))
        if config_file and Path(config_file).exists():
            self.load_from_file(config_file)
        self._apply_env_overrides()

    def load_from_file(self, config_file: str) -> None:
        """Loads configuration from a JSON file and merges with defaults."""
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            self._deep_merge(self.config, user_config)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed configuration file '{config_file}': {e}") from e
        except OSError as e:
            raise IOError(f"Failed to read configuration file '{config_file}': {e}") from e

    def _apply_env_overrides(self) -> None:
        """Applies environment variables if present."""
        if "AWS_S3_BUCKET" in os.environ:
            self.config["aws"]["s3_bucket"] = os.environ["AWS_S3_BUCKET"]
        if "AWS_DEFAULT_REGION" in os.environ:
            self.config["aws"]["region"] = os.environ["AWS_DEFAULT_REGION"]
        if "BACKUP_STORAGE_MODE" in os.environ:
            self.config["storage_mode"] = os.environ["BACKUP_STORAGE_MODE"].lower()

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """Recursively merges override dictionary into base dictionary."""
        for key, value in override.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a configuration value by top-level key."""
        return self.config.get(key, default)

    def validate(self) -> None:
        """Validates configuration sanity."""
        mode = self.config.get("storage_mode")
        if mode not in ("local", "s3"):
            raise ValueError(f"Invalid storage_mode '{mode}'. Must be 'local' or 's3'.")
        if mode == "s3" and not self.config.get("aws", {}).get("s3_bucket"):
            raise ValueError("S3 storage mode selected but aws.s3_bucket is empty.")
