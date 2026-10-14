"""
Post-restoration testing and application-level validation module (FR-19).
Executes smoke tests, syntax compilation, and configured test commands on staged restoration files.
"""

from dataclasses import dataclass, asdict, field
import json
from pathlib import Path
import py_compile
import subprocess
from typing import Any, Dict, List, Optional, Union


@dataclass
class ValidationResult:
    """Structured outcome of application-level post-restoration validation tests (FR-19)."""
    passed: bool
    tests_run: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ValidationRunner:
    """Executes application-level validation tests against staged or restored files."""

    def __init__(self, custom_command: Optional[str] = None):
        self.custom_command = custom_command

    def run_validation(self, staged_dir: Union[str, Path]) -> ValidationResult:
        """
        Runs built-in smoke tests on all files in the staged directory, followed by any custom validation command.
        """
        staged_path = Path(staged_dir).resolve()
        if not staged_path.exists():
            return ValidationResult(
                passed=False,
                tests_run=["staging_directory_check"],
                failures=[f"Staged restoration directory '{staged_dir}' does not exist."],
                reason="Staged destination missing."
            )

        tests_run: List[str] = []
        failures: List[str] = []
        details: Dict[str, Any] = {}

        # 1. Inspect all files in staged directory
        for item in staged_path.rglob("*"):
            if not item.is_file():
                continue

            rel_str = item.relative_to(staged_path).as_posix()
            suffix = item.suffix.lower()

            # Python syntax validation test
            if suffix == ".py":
                test_name = f"python_syntax_check:{rel_str}"
                tests_run.append(test_name)
                try:
                    py_compile.compile(str(item), doraise=True)
                    details[test_name] = "Compiled cleanly without syntax errors."
                except py_compile.PyCompileError as e:
                    fail_msg = f"Python syntax check failed on '{rel_str}': {e}"
                    failures.append(fail_msg)
                    details[test_name] = fail_msg

            # JSON syntax validation test
            elif suffix == ".json":
                test_name = f"json_syntax_check:{rel_str}"
                tests_run.append(test_name)
                try:
                    with open(item, "r", encoding="utf-8") as f:
                        json.load(f)
                    details[test_name] = "Valid JSON document."
                except Exception as e:
                    fail_msg = f"JSON parse error on '{rel_str}': {e}"
                    failures.append(fail_msg)
                    details[test_name] = fail_msg

            # SQL sanity validation test
            elif suffix == ".sql":
                test_name = f"sql_syntax_check:{rel_str}"
                tests_run.append(test_name)
                try:
                    content = item.read_text(encoding="utf-8")
                    if not content.strip():
                        fail_msg = f"SQL schema file '{rel_str}' is empty."
                        failures.append(fail_msg)
                        details[test_name] = fail_msg
                    else:
                        details[test_name] = f"SQL file validated ({len(content)} characters)."
                except Exception as e:
                    fail_msg = f"Error reading SQL file '{rel_str}': {e}"
                    failures.append(fail_msg)
                    details[test_name] = fail_msg

        # 2. Execute custom command if configured
        if self.custom_command:
            cmd_test_name = f"custom_validation_command:{self.custom_command}"
            tests_run.append(cmd_test_name)
            try:
                proc = subprocess.run(
                    self.custom_command,
                    shell=True,
                    cwd=str(staged_path),
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if proc.returncode != 0:
                    fail_msg = f"Custom validation command exited with code {proc.returncode}: {proc.stderr.strip()}"
                    failures.append(fail_msg)
                    details[cmd_test_name] = fail_msg
                else:
                    details[cmd_test_name] = f"Custom command passed: {proc.stdout.strip()[:100]}"
            except subprocess.TimeoutExpired:
                fail_msg = f"Custom validation command timed out after 30 seconds."
                failures.append(fail_msg)
                details[cmd_test_name] = fail_msg
            except Exception as e:
                fail_msg = f"Error executing custom validation command: {e}"
                failures.append(fail_msg)
                details[cmd_test_name] = fail_msg

        # If no specific file tests matched, ensure at least directory non-empty check ran
        if not tests_run:
            tests_run.append("directory_contains_files")
            files = list(staged_path.rglob("*"))
            if files:
                details["directory_contains_files"] = f"Found {len(files)} items in staged directory."
            else:
                failures.append("Staged directory contains zero files.")
                details["directory_contains_files"] = "Empty staged directory."

        passed = len(failures) == 0
        reason = "All post-restoration validation tests passed." if passed else "One or more validation checks failed."

        return ValidationResult(
            passed=passed,
            tests_run=tests_run,
            failures=failures,
            details=details,
            reason=reason
        )
