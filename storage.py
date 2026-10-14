"""
Storage abstraction module supporting local filesystem storage and AWS S3 storage (FR-03).
Provides unified interfaces for uploading, downloading, listing, and reading backup objects and manifests.
"""

from abc import ABC, abstractmethod
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional


class StorageBackend(ABC):
    """Abstract storage backend for backup objects, manifests, and reports."""

    @abstractmethod
    def upload_file(self, local_path: Path, storage_key: str) -> str:
        """Uploads a local file to the storage backend and returns the storage reference."""
        pass

    @abstractmethod
    def download_file(self, storage_key: str, local_destination: Path) -> Path:
        """Downloads an object to a local filesystem destination."""
        pass

    @abstractmethod
    def read_text(self, storage_key: str) -> str:
        """Reads a text object (e.g. JSON manifest) from storage."""
        pass

    @abstractmethod
    def write_text(self, storage_key: str, content: str) -> str:
        """Writes text content to a storage key."""
        pass

    @abstractmethod
    def list_objects(self, prefix: str = "") -> List[str]:
        """Lists object keys matching prefix."""
        pass

    @abstractmethod
    def object_exists(self, storage_key: str) -> bool:
        """Checks if an object exists in storage."""
        pass

    @abstractmethod
    def delete_object(self, storage_key: str) -> bool:
        """Deletes an object (used primarily in cleanup routines)."""
        pass


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage implementation for local mode, offline testing, and grading (SRS Section 11.1)."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, key: str) -> Path:
        """Safely resolves storage key within base_dir, preventing directory escape."""
        clean_key = str(key).strip("/\\").replace("\\", "/")
        full_path = (self.base_dir / clean_key).resolve()
        if not str(full_path).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal detected: '{key}' escapes base directory '{self.base_dir}'")
        return full_path

    def upload_file(self, local_path: Path, storage_key: str) -> str:
        src = Path(local_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Source file not found for upload: {local_path}")
        dest = self._resolve_safe_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return storage_key

    def download_file(self, storage_key: str, local_destination: Path) -> Path:
        src = self._resolve_safe_path(storage_key)
        if not src.is_file():
            raise FileNotFoundError(f"Storage object not found: {storage_key}")
        dest = Path(local_destination).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return dest

    def read_text(self, storage_key: str) -> str:
        target = self._resolve_safe_path(storage_key)
        if not target.is_file():
            raise FileNotFoundError(f"Storage object not found: {storage_key}")
        return target.read_text(encoding="utf-8")

    def write_text(self, storage_key: str, content: str) -> str:
        dest = self._resolve_safe_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return storage_key

    def list_objects(self, prefix: str = "") -> List[str]:
        keys: List[str] = []
        clean_prefix = prefix.strip("/\\").replace("\\", "/")
        search_root = (self.base_dir / clean_prefix).resolve()
        if not str(search_root).startswith(str(self.base_dir)):
            return []
        if not search_root.exists():
            return []
        for root, _, files in os.walk(search_root):
            for file in files:
                p = (Path(root) / file).resolve()
                rel = p.relative_to(self.base_dir).as_posix()
                keys.append(rel)
        return sorted(keys)

    def object_exists(self, storage_key: str) -> bool:
        dest = self._resolve_safe_path(storage_key)
        return dest.is_file()

    def delete_object(self, storage_key: str) -> bool:
        dest = self._resolve_safe_path(storage_key)
        if dest.is_file():
            dest.unlink()
            return True
        return False


class S3StorageBackend(StorageBackend):
    """Amazon S3 storage backend using boto3 (SRS Section 11.1 & Master Prompt Section 3.2)."""

    def __init__(self, bucket_name: str, region_name: str = "us-east-1", s3_client: Optional[Any] = None):
        self.bucket_name = bucket_name
        self.region_name = region_name

        if s3_client is not None:
            self.s3 = s3_client
        else:
            try:
                import boto3
                self.s3 = boto3.client("s3", region_name=region_name)
            except Exception as e:
                raise RuntimeError(f"Failed to initialize S3 client: {e}") from e

    def upload_file(self, local_path: Path, storage_key: str) -> str:
        src = Path(local_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Source file not found for S3 upload: {local_path}")
        clean_key = storage_key.strip("/\\").replace("\\", "/")
        try:
            self.s3.upload_file(
                Filename=str(src),
                Bucket=self.bucket_name,
                Key=clean_key,
                ExtraArgs={"ServerSideEncryption": "AES256"}
            )
            return clean_key
        except Exception as e:
            raise IOError(f"Failed to upload '{src}' to S3 key 's3://{self.bucket_name}/{clean_key}': {e}") from e

    def download_file(self, storage_key: str, local_destination: Path) -> Path:
        clean_key = storage_key.strip("/\\").replace("\\", "/")
        dest = Path(local_destination).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.s3.download_file(
                Bucket=self.bucket_name,
                Key=clean_key,
                Filename=str(dest)
            )
            return dest
        except Exception as e:
            raise IOError(f"Failed to download S3 key 's3://{self.bucket_name}/{clean_key}' to '{dest}': {e}") from e

    def read_text(self, storage_key: str) -> str:
        clean_key = storage_key.strip("/\\").replace("\\", "/")
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=clean_key)
            return response["Body"].read().decode("utf-8")
        except Exception as e:
            raise IOError(f"Failed to read S3 text object 's3://{self.bucket_name}/{clean_key}': {e}") from e

    def write_text(self, storage_key: str, content: str) -> str:
        clean_key = storage_key.strip("/\\").replace("\\", "/")
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=clean_key,
                Body=content.encode("utf-8"),
                ContentType="application/json",
                ServerSideEncryption="AES256"
            )
            return clean_key
        except Exception as e:
            raise IOError(f"Failed to write text to S3 key 's3://{self.bucket_name}/{clean_key}': {e}") from e

    def list_objects(self, prefix: str = "") -> List[str]:
        clean_prefix = prefix.strip("/\\").replace("\\", "/")
        keys: List[str] = []
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=clean_prefix):
                for item in page.get("Contents", []):
                    keys.append(item["Key"])
            return sorted(keys)
        except Exception as e:
            raise IOError(f"Failed to list objects in S3 bucket '{self.bucket_name}' with prefix '{prefix}': {e}") from e

    def object_exists(self, storage_key: str) -> bool:
        clean_key = storage_key.strip("/\\").replace("\\", "/")
        try:
            self.s3.head_object(Bucket=self.bucket_name, Key=clean_key)
            return True
        except Exception:
            return False

    def delete_object(self, storage_key: str) -> bool:
        clean_key = storage_key.strip("/\\").replace("\\", "/")
        try:
            self.s3.delete_object(Bucket=self.bucket_name, Key=clean_key)
            return True
        except Exception:
            return False
