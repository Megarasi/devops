# Intelligent Backup and Restoration System
## Dependency-Aware Compatibility Validation and Automatic Fallback

**Hackathon:** DEVSPRINT2026  
**Team Name:** CODE LOGGERS  
**Team Members:** LOGANARAYANAN S & MEGARASI S  
**Department:** Artificial Intelligence and Machine Learning (AIML)  
**Version:** 1.0.0  

---

## 1. Project Overview

Creating a backup copy of a file alone does not guarantee that the file can be recovered without corruption, or that related files will function together after restoration.

The **Intelligent Backup and Restoration System** is a production-grade, evidence-based CLI application that solves these critical challenges:
1. **Cryptographic Integrity Verification (SHA-256):** Every backup object is verified against its trusted expected checksum calculated using streaming 64 KB buffers.
2. **Evidence-Based Automatic Fallback:** If the newest backup candidate is corrupted or fails integrity, the system automatically rejects it and deterministically falls back to an older verified backup version.
3. **Dependency-Aware Compatibility Validation:** Validates cross-component rules (e.g., Application Backend v2 requires Database Schema v2). The system understands that even if two files pass individual SHA-256 checks, an incompatible combination must be rejected.
4. **Deterministic Multi-Version Recovery Solver:** Selects the newest compatible recovery set satisfying all cross-component constraints.
5. **Isolated Restoration Staging:** Restores candidate files to an isolated directory before modifying any working files.
6. **Post-Restoration Application Smoke Testing:** Runs syntax checks (`py_compile`), SQL schema sanity checks, and custom test commands on restored files.
7. **Comprehensive Audit Evidence Reporting:** Generates machine-readable JSON (`report.json`) and human-readable Markdown (`report.md`) reports keeping Integrity, Compatibility, and Validation strictly separate.

---

## 2. Architecture & Modules

The application consists of 11 discrete, single-responsibility modules:

- [`intelligent_backup_system/backup.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/backup.py): File selection, path validation, timestamping, streaming SHA-256 computation, and backup registration.
- [`intelligent_backup_system/verify.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/verify.py): SHA-256 checksum computation using chunked 64 KB buffers and integrity verification.
- [`intelligent_backup_system/manifest_manager.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/manifest_manager.py): Atomic JSON manifest management and historical snapshotting.
- [`intelligent_backup_system/storage.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/storage.py): Storage provider abstraction supporting local filesystem storage and Amazon S3 with SSE-AES256.
- [`intelligent_backup_system/compatibility.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/compatibility.py): Dependency rule engine and cross-component compatibility validator.
- [`intelligent_backup_system/recovery.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/recovery.py): Multi-version recovery solver with automatic fallback.
- [`intelligent_backup_system/restore.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/restore.py): Safe isolated staging, post-restoration verification, and promotion.
- [`intelligent_backup_system/validation.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/validation.py): Post-restoration application smoke tests (Python syntax, SQL sanity, JSON validation).
- [`intelligent_backup_system/report.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/report.py): JSON and Markdown recovery evidence report generator.
- [`intelligent_backup_system/config_manager.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/config_manager.py): Configuration loader and validator.
- [`intelligent_backup_system/logging_config.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/logging_config.py): Structured dual logging (`logs/backup.log` and `logs/recovery.log`).
- [`intelligent_backup_system/main.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/intelligent_backup_system/main.py): Unified CLI entry point.

---

## 3. Installation & Prerequisites

### Prerequisites
- Python 3.10+ (tested on Python 3.12.14)
- Git (optional)

### Setup Instructions

```bash
# 1. Clone or navigate to the project directory
cd /path/to/devsprint

# 2. Create and activate a Python virtual environment
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## 4. CLI Usage Guide

The application provides an intuitive command-line interface:

### 4.1 System Health Check
Verifies storage accessibility, configuration files, and dependency rules:
```bash
python -m intelligent_backup_system.main health-check
```

### 4.2 Creating a Backup
Creates a timestamped backup of selected files or directories:
```bash
python -m intelligent_backup_system.main backup \
    --paths ./sample_data/backend/app.py \
    --component backend \
    --version 1.0.0
```

### 4.3 Listing Available Backups
Lists all registered backups in chronological order:
```bash
python -m intelligent_backup_system.main list-backups
```
Filter by component:
```bash
python -m intelligent_backup_system.main list-backups --component backend
```

### 4.4 Verifying Backup Integrity
Verifies the cryptographic SHA-256 integrity of an existing backup:
```bash
python -m intelligent_backup_system.main verify --backup-id <BACKUP_UUID>
```

### 4.5 Cross-Component Compatibility Check
Evaluates whether a proposed set of components satisfies dependency rules:
```bash
# Compatible check:
python -m intelligent_backup_system.main compatibility-check \
    --components backend=2.0.0 database=2.0.0

# Incompatible check:
python -m intelligent_backup_system.main compatibility-check \
    --components backend=2.0.0 database=1.0.0
```

### 4.6 Intelligent Recovery with Automatic Fallback
Discovers candidates, validates integrity, verifies compatibility, stages files, runs smoke tests, and generates reports:
```bash
python -m intelligent_backup_system.main recover \
    --components backend,database \
    --staging ./staging_area
```
To promote verified files into a live working directory:
```bash
python -m intelligent_backup_system.main recover \
    --components backend,database \
    --staging ./staging_area \
    --working-dir ./live_app \
    --promote
```

### 4.7 Viewing Recovery Evidence Reports
Displays the human-readable Markdown recovery audit report:
```bash
python -m intelligent_backup_system.main report --recovery-id <RECOVERY_UUID>
```

---

## 5. Demonstration Scenarios (SRS Section 14)

All four demonstration scenarios in the SRS are fully implemented as automated tests in [`tests/test_recovery_scenarios.py`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/tests/test_recovery_scenarios.py):

| Scenario | Objective | Execution Command | Result |
| :--- | :--- | :--- | :--- |
| **Scenario A** | Normal Recovery: Backup sample files, simulate deletion, restore to isolated staging, verify SHA-256. | `pytest tests/test_recovery_scenarios.py -k test_scenario_a` | **PASSED** (Overall: SUCCESS) |
| **Scenario B** | Corrupted Newest Backup: Newest candidate fails integrity; system automatically falls back to older verified backup. | `pytest tests/test_recovery_scenarios.py -k test_scenario_b` | **PASSED** (Overall: SUCCESS with fallback) |
| **Scenario C** | Individually Valid but Incompatible Versions: Files pass SHA-256 checks but fail cross-component compatibility rules; set rejected. | `pytest tests/test_recovery_scenarios.py -k test_scenario_c` | **PASSED** (Overall: FAILED, safe abort) |
| **Scenario D** | Compatible Recovery Set Selection: Multi-version solver rejects incompatible combination and selects newest compatible set. | `pytest tests/test_recovery_scenarios.py -k test_scenario_d` | **PASSED** (Overall: SUCCESS) |

---

## 6. Automated Testing & Verification

Run the complete test suite (53 tests across 12 test files):

```bash
# Run all tests with verbose output:
pytest -v tests/

# Run tests with code coverage analysis:
pytest --cov=intelligent_backup_system --cov-report=term-missing tests/
```

Test Results: **53 passed in ~3.0s (100% pass rate)**. Full report saved in [`test_results.txt`](file:///c:/Users/megar/OneDrive/Desktop/devsprint/test_results.txt).
