from __future__ import annotations

import hashlib
import logging
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from orchestack_storage.config import StorageConfig

logger = logging.getLogger(__name__)

# Default buckets per RFC-001.
BUCKET_MEMORY = "homarus-memory"
BUCKET_ARTIFACTS = "homarus-artifacts"
BUCKET_AUDIT = "homarus-audit-export"


class ChecksumMismatchError(Exception):
    """Raised when a downloaded object's SHA-256 does not match the expected value."""


class StorageClient:
    """Thin wrapper around boto3 S3 client for MinIO-compatible storage.

    Provides put/get/list/delete with automatic SHA-256 checksums and
    payload_ref URI generation (s3://<bucket>/<key>).
    """

    def __init__(self, config: StorageConfig | None = None) -> None:
        cfg = config or StorageConfig.from_env()
        self._s3 = boto3.client(
            "s3",
            endpoint_url=cfg.endpoint,
            aws_access_key_id=cfg.access_key,
            aws_secret_access_key=cfg.secret_key,
            region_name=cfg.region,
            use_ssl=cfg.use_ssl,
            config=BotoConfig(signature_version="s3v4"),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes | str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Store an object and return its payload_ref and sha256 digest."""
        if isinstance(data, str):
            data = data.encode("utf-8")

        sha256 = hashlib.sha256(data).hexdigest()

        extra: dict[str, Any] = {}
        meta = dict(metadata or {})
        meta["sha256"] = sha256
        extra["Metadata"] = meta

        self._s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            **extra,
        )

        payload_ref = f"s3://{bucket}/{key}"
        logger.debug("put %s (%d bytes, sha256=%s)", payload_ref, len(data), sha256)

        return {
            "payload_ref": payload_ref,
            "sha256": sha256,
            "size": len(data),
        }

    def get_object(
        self,
        bucket: str,
        key: str,
        expected_sha256: str | None = None,
    ) -> bytes:
        """Retrieve an object. Optionally verify its SHA-256 digest."""
        resp = self._s3.get_object(Bucket=bucket, Key=key)
        data = resp["Body"].read()

        if expected_sha256:
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected_sha256:
                raise ChecksumMismatchError(
                    f"SHA-256 mismatch for s3://{bucket}/{key}: expected {expected_sha256}, got {actual}"
                )

        return data

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        max_keys: int = 1000,
    ) -> list[dict[str, Any]]:
        """List objects in a bucket under an optional prefix."""
        resp = self._s3.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            MaxKeys=max_keys,
        )
        contents = resp.get("Contents", [])
        return [
            {
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
                "payload_ref": f"s3://{bucket}/{obj['Key']}",
            }
            for obj in contents
        ]

    def delete_object(self, bucket: str, key: str) -> None:
        """Delete an object from a bucket."""
        self._s3.delete_object(Bucket=bucket, Key=key)
        logger.debug("deleted s3://%s/%s", bucket, key)

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        """Return metadata for an object without downloading its body."""
        resp = self._s3.head_object(Bucket=bucket, Key=key)
        meta = resp.get("Metadata", {})
        return {
            "payload_ref": f"s3://{bucket}/{key}",
            "size": resp["ContentLength"],
            "content_type": resp["ContentType"],
            "sha256": meta.get("sha256", ""),
            "last_modified": resp["LastModified"].isoformat(),
        }

    def ensure_bucket(self, bucket: str) -> None:
        """Create a bucket if it does not already exist."""
        try:
            self._s3.head_bucket(Bucket=bucket)
        except self._s3.exceptions.ClientError:
            self._s3.create_bucket(Bucket=bucket)
            logger.info("created bucket %s", bucket)

    @staticmethod
    def payload_ref(bucket: str, key: str) -> str:
        """Generate an RFC-001 payload_ref URI."""
        return f"s3://{bucket}/{key}"
