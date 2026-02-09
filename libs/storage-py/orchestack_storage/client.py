"""S3-compatible storage client wrapping boto3."""

from __future__ import annotations

import hashlib
from typing import Any

import boto3


class StorageClient:
    """S3-compatible object storage client with checksum verification."""

    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, region: str = "us-east-1"):
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def put_object(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store object with SHA-256 checksum. Returns payload_ref URI."""
        sha256 = hashlib.sha256(data).hexdigest()
        self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata={"sha256": sha256},
        )
        return f"s3://{bucket}/{key}"

    def get_object(self, bucket: str, key: str) -> bytes:
        """Retrieve object and verify checksum."""
        response = self._client.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()
        stored_sha = response.get("Metadata", {}).get("sha256")
        if stored_sha:
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != stored_sha:
                raise ValueError(f"Checksum mismatch: expected {stored_sha}, got {actual_sha}")
        return data

    def list_objects(self, bucket: str, prefix: str = "") -> list[dict[str, Any]]:
        """List objects in bucket with optional prefix."""
        response = self._client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        return response.get("Contents", [])

    def delete_object(self, bucket: str, key: str) -> None:
        """Delete an object."""
        self._client.delete_object(Bucket=bucket, Key=key)

    @staticmethod
    def payload_ref(bucket: str, key: str) -> str:
        """Generate RFC-001 §6.2 payload_ref URI."""
        return f"s3://{bucket}/{key}"
