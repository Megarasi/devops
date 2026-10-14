"""
Integrity verification module for Intelligent Backup and Restoration System.
Calculates SHA-256 checksums using chunked streaming and verifies backup/restored files (FR-04, FR-06, FR-08).
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, Union


# Default buffer size: 64 KB (optimal for streaming without memory overhead)
CHUNK_SIZE_BYTES = 64 * 1024


@dataclass
class VerificationResult:
    """Represents the structured outcome of a cryptographic integrity verification check."""
    file_identifier: str
    expected_hash: str
    actual_hash: str
    passed: bool
    reason: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Converts result to dictionary for JSON reports and logging."""
        return asdict(self)


def calculate_sha256(file_path: Union[str, Path], chunk_size: int = CHUNK_SIZE_BYTES) -> str:
    """
    Computes the SHA-256 digest of a local file using chunked streaming reads (FR-04).
    Prevents loading entire multi-megabyte or multi-gigabyte files into memory.

    Args:
        file_path: Path to the target file.
        chunk_size: Size of stream buffers (default 64 KB).

    Returns:
        Hexadecimal SHA-256 digest.

    Raises:
        FileNotFoundError: If target file does not exist.
        PermissionError: If file cannot be read due to permissions.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Cannot calculate checksum: File not found at '{file_path}'")

    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)

    return hasher.hexdigest()


def calculate_bytes_sha256(data: bytes) -> str:
    """Computes SHA-256 checksum for byte streams."""
    return hashlib.sha256(data).hexdigest()


def verify_backup_integrity(
    file_identifier: str,
    actual_content_or_hash: Union[str, bytes, Path],
    expected_hash: str,
    is_already_hash: bool = False
) -> VerificationResult:
    """
    Compares the calculated SHA-256 checksum with the trusted expected checksum (FR-06).
    
    Args:
        file_identifier: Human-readable file name, relative path, or candidate ID.
        actual_content_or_hash: File path, byte content, or precomputed hash.
        expected_hash: Trusted expected SHA-256 checksum from the manifest.
        is_already_hash: If True, actual_content_or_hash is treated as a hex hash string.

    Returns:
        VerificationResult detailing pass/fail status and audit reason.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    expected = expected_hash.strip().lower()

    try:
        if is_already_hash:
            actual = str(actual_content_or_hash).strip().lower()
        elif isinstance(actual_content_or_hash, (bytes, bytearray)):
            actual = calculate_bytes_sha256(actual_content_or_hash)
        else:
            actual = calculate_sha256(actual_content_or_hash)

        if actual == expected:
            return VerificationResult(
                file_identifier=str(file_identifier),
                expected_hash=expected,
                actual_hash=actual,
                passed=True,
                reason="SHA-256 checksum matches trusted manifest digest exactly.",
                timestamp=now_iso
            )
        else:
            return VerificationResult(
                file_identifier=str(file_identifier),
                expected_hash=expected,
                actual_hash=actual,
                passed=False,
                reason=f"Integrity violation: Calculated digest ({actual[:12]}...) does not match expected ({expected[:12]}...).",
                timestamp=now_iso
            )
    except Exception as e:
        return VerificationResult(
            file_identifier=str(file_identifier),
            expected_hash=expected,
            actual_hash="",
            passed=False,
            reason=f"Integrity check failed due to exception: {str(e)}",
            timestamp=now_iso
        )


def verify_restored_file(restored_file_path: Union[str, Path], expected_hash: str) -> VerificationResult:
    """
    Verifies that a restored file on disk matches its expected SHA-256 digest (FR-08).
    """
    return verify_backup_integrity(
        file_identifier=str(restored_file_path),
        actual_content_or_hash=restored_file_path,
        expected_hash=expected_hash,
        is_already_hash=False
    )
