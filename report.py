"""
Recovery evidence report generation module (FR-20, SRS Section 5.3).
Generates machine-readable JSON and human-readable Markdown audit reports,
keeping integrity, compatibility, and application validation strictly separated.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from intelligent_backup_system.recovery import RecoveryExecutionRecord
from intelligent_backup_system.storage import StorageBackend


class ReportGenerator:
    """Generates and persists recovery evidence reports in JSON and Markdown formats (FR-20)."""

    def __init__(self, storage: Optional[StorageBackend] = None, reports_dir: str = "reports"):
        self.storage = storage
        self.reports_dir = Path(reports_dir).resolve()
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_json_report(self, record: RecoveryExecutionRecord) -> str:
        """Serializes RecoveryExecutionRecord into formatted JSON string."""
        data = record.to_dict()
        data["report_generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        data["system_information"] = {
            "hackathon": "DEVSPRINT2026",
            "team": "CODE LOGGERS",
            "authors": ["LOGANARAYANAN S", "MEGARASI S"],
            "department": "AIML"
        }
        return json.dumps(data, indent=2)

    def generate_markdown_report(self, record: RecoveryExecutionRecord) -> str:
        """Creates a human-readable Markdown audit report."""
        sel = record.selected_combination
        overall_badge = f"[{record.overall_status}]"

        lines = [
            f"# Recovery Evidence Report",
            f"**Hackathon:** DEVSPRINT2026 | **Team:** CODE LOGGERS | **Status:** {overall_badge}",
            f"",
            f"---",
            f"",
            f"## 1. Recovery Session Overview",
            f"- **Recovery ID:** `{record.recovery_id}`",
            f"- **Started At (UTC):** `{record.started_at}`",
            f"- **Completed At (UTC):** `{record.completed_at}`",
            f"- **Requested Components:** {', '.join(f'`{c}`' for c in record.requested_components)}",
            f"- **Candidate Combinations Evaluated:** {record.candidates_considered_count}",
            f"- **Isolated Staging Location:** `{record.isolated_staging_path}`",
            f"- **Promoted to Live Working Files:** {'Yes' if record.promoted_to_working else 'No'}",
            f"- **Overall Status:** **`{record.overall_status}`**",
            f"",
            f"---",
            f"",
            f"## 2. Separate Status Evaluation Summary (SRS Section 5.3)",
            f"",
            f"| Verification Tier | Result | Status Meaning / Criteria |",
            f"| :--- | :--- | :--- |"
        ]

        # Integrity Status
        if sel:
            lines.append(f"| **1. Cryptographic Integrity** | **`{sel.integrity_status}`** | SHA-256 digests match trusted manifest values. |")
            lines.append(f"| **2. Cross-Component Compatibility** | **`{sel.compatibility_status}`** | Component versions satisfy all dependency rules. |")
            lines.append(f"| **3. Post-Restore Validation** | **`{sel.validation_status}`** | Application smoke tests and syntax checks passed. |")
        else:
            lines.append(f"| **1. Cryptographic Integrity** | **`EVALUATED / REJECTED`** | Candidates evaluated failed checksum checks or were exhausted. |")
            lines.append(f"| **2. Cross-Component Compatibility** | **`FAIL / UNMET`** | No combination satisfied both integrity and dependency rules. |")
            lines.append(f"| **3. Post-Restore Validation** | **`NOT EVALUATED`** | Blocked due to lack of verified compatible candidates. |")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 3. Selected Recovery Set",
        ])

        if sel:
            lines.extend([
                f"- **Combination ID:** `{sel.combination_id}`",
                f"- **Selected Component Versions:**",
            ])
            for comp, ver in sel.component_versions.items():
                lines.append(f"  - `{comp}`: version `{ver}`")
            lines.append(f"- **Selection Rationale:** Candidate set satisfied cryptographic SHA-256 integrity, passed cross-component compatibility matrix, and passed all post-restoration application smoke tests.")
            lines.append(f"- **Restored Files in Isolated Staging:**")
            for f in record.restored_files:
                lines.append(f"  - `{f}`")
        else:
            lines.append(f"[WARNING] No candidate set was selected. All evaluated candidates failed integrity verification or violated compatibility rules.")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 4. Evaluated Candidate Sets & Automatic Fallback Timeline",
            f"",
            f"| Combination ID | Component Versions | Integrity | Compatibility | Validation | Decision | Rationale / Failure Reason |",
            f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        ])

        for ev in record.evaluated_combinations:
            vers_str = ", ".join(f"{k}:{v}" for k, v in ev.component_versions.items())
            decision_badge = f"[{ev.decision}]"
            reason_str = ev.rejection_reason or "Candidate set passed all criteria and was selected."
            lines.append(f"| `{ev.combination_id}` | `{vers_str}` | `{ev.integrity_status}` | `{ev.compatibility_status}` | `{ev.validation_status}` | **{decision_badge}** | {reason_str} |")

        if record.unresolved_errors:
            lines.extend([
                f"",
                f"---",
                f"",
                f"## 5. Unresolved Errors",
            ])
            for err in record.unresolved_errors:
                lines.append(f"- [ERROR] {err}")

        lines.extend([
            f"",
            f"---",
            f"*Report generated automatically by CODE LOGGERS Intelligent Backup System v1.0.0*"
        ])

        return "\n".join(lines)

    def save_reports(self, record: RecoveryExecutionRecord) -> Tuple[Path, Path]:
        """
        Saves both JSON and Markdown reports to the reports directory and storage backend (FR-20).

        Returns:
            Tuple of (json_file_path, markdown_file_path).
        """
        rec_dir = self.reports_dir / record.recovery_id
        rec_dir.mkdir(parents=True, exist_ok=True)

        json_path = rec_dir / "report.json"
        md_path = rec_dir / "report.md"

        json_content = self.generate_json_report(record)
        md_content = self.generate_markdown_report(record)

        json_path.write_text(json_content, encoding="utf-8")
        md_path.write_text(md_content, encoding="utf-8")

        # Upload to storage backend if available
        if self.storage:
            s_json_key = f"reports/{record.recovery_id}/report.json"
            s_md_key = f"reports/{record.recovery_id}/report.md"
            try:
                self.storage.write_text(s_json_key, json_content)
                self.storage.write_text(s_md_key, md_content)
            except Exception:
                pass

        return json_path, md_path
