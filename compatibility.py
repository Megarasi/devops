"""
Dependency and compatibility validation module for Intelligent Backup and Restoration System (FR-14, FR-15, FR-16).
Parses cross-component dependency rules and evaluates proposed recovery candidate sets.
"""

from dataclasses import dataclass, asdict, field
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union


def parse_version_tuple(version_str: str) -> Tuple[int, ...]:
    """
    Parses a version string (e.g. '2.0.0', '1.2', 'v2') into a comparable tuple of integers.
    Non-numeric suffixes are stripped or converted cleanly.
    """
    cleaned = re.sub(r"^[vV]", "", str(version_str).strip())
    tokens = re.split(r"[.\-_]", cleaned)
    numeric_tokens: List[int] = []
    for t in tokens:
        match = re.search(r"^\d+", t)
        if match:
            numeric_tokens.append(int(match.group()))
        else:
            break
    return tuple(numeric_tokens) if numeric_tokens else (0,)


@dataclass
class VersionConstraint:
    """Represents version requirements for a dependency."""
    exact_version: Optional[str] = None
    min_version: Optional[str] = None
    max_version: Optional[str] = None
    description: str = ""

    def is_satisfied_by(self, version_str: str) -> Tuple[bool, str]:
        """
        Evaluates whether version_str satisfies this constraint.
        Returns (True, "OK") or (False, reason).
        """
        v_tuple = parse_version_tuple(version_str)

        if self.exact_version:
            exact_tuple = parse_version_tuple(self.exact_version)
            if v_tuple != exact_tuple:
                return False, f"Requires exact version {self.exact_version}, but found {version_str}"

        if self.min_version:
            min_tuple = parse_version_tuple(self.min_version)
            if v_tuple < min_tuple:
                return False, f"Requires minimum version {self.min_version}, but found {version_str}"

        if self.max_version:
            max_tuple = parse_version_tuple(self.max_version)
            if v_tuple > max_tuple:
                return False, f"Requires maximum version {self.max_version}, but found {version_str}"

        return True, "Satisfied"


@dataclass
class CompatibilityResult:
    """Structured outcome of a compatibility evaluation across a recovery set (FR-16)."""
    compatible: bool
    component_versions: Dict[str, str]
    violations: List[str] = field(default_factory=list)
    rules_checked: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DependencyManager:
    """Manages and validates dependency rules configured in dependency_rules.json (FR-14, FR-15)."""

    def __init__(self, rules_file: Optional[Union[str, Path]] = None):
        self.rules: List[Dict[str, Any]] = []
        if rules_file:
            self.load_rules(rules_file)

    def load_rules(self, rules_file: Union[str, Path]) -> None:
        """Loads and validates dependency rules from a JSON file."""
        path = Path(rules_file)
        if not path.is_file():
            raise FileNotFoundError(f"Dependency rules configuration file not found: '{rules_file}'")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_rules = data.get("rules", [])
            if not isinstance(raw_rules, list):
                raise ValueError("Malformed dependency rules: 'rules' must be a list.")
            self.rules = raw_rules
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON in dependency rules '{rules_file}': {e}") from e

    def validate_set(
        self,
        component_versions: Dict[str, str],
        require_all_dependencies: bool = False
    ) -> CompatibilityResult:
        """
        Evaluates a proposed candidate set against all configured dependency rules (FR-16).
        
        Args:
            component_versions: Mapping of component_name -> component_version
                                (e.g. {"backend": "2.0.0", "database": "1.0.0"})
            require_all_dependencies: If True, missing dependencies in the set trigger a violation.
                                      If False, dependencies not present in component_versions are not checked.

        Returns:
            CompatibilityResult detailing compatibility and any rule violations.
        """
        violations: List[str] = []
        rules_checked = 0

        # Normalize component keys to lowercase for robust matching
        normalized_versions = {k.lower(): str(v) for k, v in component_versions.items()}

        for rule in self.rules:
            rule_comp = rule.get("component", "").lower()
            rule_ver_str = rule.get("version", "")
            requires = rule.get("requires", {})

            if rule_comp not in normalized_versions:
                continue

            current_comp_ver = normalized_versions[rule_comp]

            # Check if this rule applies to the version of the component in the candidate set
            if rule_ver_str:
                rule_ver_tuple = parse_version_tuple(rule_ver_str)
                current_ver_tuple = parse_version_tuple(current_comp_ver)
                # If rule specifies exact version, check for match
                if rule_ver_tuple != current_ver_tuple:
                    continue

            # Evaluate each required dependency in this rule
            for dep_comp, constraint_dict in requires.items():
                rules_checked += 1
                dep_comp_norm = dep_comp.lower()

                if dep_comp_norm not in normalized_versions:
                    if require_all_dependencies:
                        violations.append(
                            f"Missing required dependency: '{rule_comp}' v{current_comp_ver} requires '{dep_comp}', "
                            f"which is not included in the recovery set."
                        )
                    continue

                dep_actual_ver = normalized_versions[dep_comp_norm]
                constraint = VersionConstraint(
                    exact_version=constraint_dict.get("exact_version"),
                    min_version=constraint_dict.get("min_version"),
                    max_version=constraint_dict.get("max_version"),
                    description=constraint_dict.get("description", "")
                )

                satisfied, failure_reason = constraint.is_satisfied_by(dep_actual_ver)
                if not satisfied:
                    desc_extra = f" ({constraint.description})" if constraint.description else ""
                    violations.append(
                        f"Compatibility violation: '{rule_comp}' v{current_comp_ver} requires '{dep_comp}' "
                        f"matching constraint [{failure_reason}]{desc_extra}."
                    )

        if violations:
            return CompatibilityResult(
                compatible=False,
                component_versions=component_versions,
                violations=violations,
                rules_checked=rules_checked,
                reason="One or more cross-component dependency constraints were violated."
            )
        else:
            return CompatibilityResult(
                compatible=True,
                component_versions=component_versions,
                violations=[],
                rules_checked=rules_checked,
                reason="All configured cross-component dependency rules passed successfully."
            )
