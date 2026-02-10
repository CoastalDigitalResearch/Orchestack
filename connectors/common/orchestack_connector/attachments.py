"""Attachment handling - upload/download via MinIO (S3-compatible)."""

from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
from datetime import timedelta

from minio import Minio  # type: ignore[import-untyped]

from orchestack_connector.message import AttachmentRef

logger = logging.getLogger(__name__)

# Default upper bound per attachment (bytes).
_DEFAULT_MAX_SIZE = 10 * 1024 * 1024  # 10 MiB


class AttachmentTooLargeError(Exception):
    """Raised when an attachment exceeds the configured size limit."""


class AttachmentManager:
    """Upload and download attachments through MinIO.

    Parameters
    ----------
    endpoint:
        MinIO host:port (e.g. ``localhost:9000``).
    access_key / secret_key:
        Credentials.
    bucket:
        Target bucket name.  Created automatically if it does not exist.
    secure:
        Use TLS.
    max_size_bytes:
        Hard limit per attachment.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str = "orchestack-attachments",
        secure: bool = False,
        max_size_bytes: int = _DEFAULT_MAX_SIZE,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket
        self._max_size = max_size_bytes

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ensure_bucket(self) -> None:
        """Create the bucket if it does not already exist."""
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
            logger.info("Created MinIO bucket: %s", self._bucket)

    # ------------------------------------------------------------------
    # Ingress  (platform bytes  -->  S3 object  -->  AttachmentRef)
    # ------------------------------------------------------------------

    def upload(
        self,
        object_key: str,
        data: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> AttachmentRef:
        """Upload raw bytes to MinIO and return an :class:`AttachmentRef`.

        Parameters
        ----------
        object_key:
            Full S3 key (e.g. ``discord/123/att_456.png``).
        data:
            Raw attachment bytes.
        filename:
            Original filename from the platform.
        content_type:
            MIME type.  Auto-detected from *filename* when ``None``.

        Raises
        ------
        AttachmentTooLargeError
            When ``len(data)`` exceeds the configured limit.
        """
        size = len(data)
        if size > self._max_size:
            raise AttachmentTooLargeError(f"Attachment {filename!r} is {size} bytes; limit is {self._max_size}")

        if content_type is None:
            content_type = self._detect_content_type(filename)

        sha256 = hashlib.sha256(data).hexdigest()

        self._client.put_object(
            bucket_name=self._bucket,
            object_name=object_key,
            data=io.BytesIO(data),
            length=size,
            content_type=content_type,
            metadata={"x-amz-meta-sha256": sha256},
        )
        logger.debug("Uploaded %s (%d bytes, sha256=%s)", object_key, size, sha256)

        return AttachmentRef(
            filename=filename,
            content_type=content_type,
            size_bytes=size,
            payload_ref=f"s3://{self._bucket}/{object_key}",
        )

    # ------------------------------------------------------------------
    # Egress  (AttachmentRef  -->  bytes)
    # ------------------------------------------------------------------

    def download(self, ref: AttachmentRef) -> bytes:
        """Download an attachment from MinIO and verify its checksum.

        Parameters
        ----------
        ref:
            An :class:`AttachmentRef` whose ``payload_ref`` starts with
            ``s3://<bucket>/``.

        Returns
        -------
        bytes
            Raw file content.
        """
        object_key = self._ref_to_key(ref.payload_ref)
        response = self._client.get_object(self._bucket, object_key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()

        logger.debug("Downloaded %s (%d bytes)", object_key, len(data))
        return data

    def presigned_url(self, ref: AttachmentRef, expires: timedelta | None = None) -> str:
        """Return a presigned GET URL for the attachment.

        Parameters
        ----------
        ref:
            Attachment reference.
        expires:
            URL lifetime.  Defaults to 1 hour.
        """
        if expires is None:
            expires = timedelta(hours=1)
        object_key = self._ref_to_key(ref.payload_ref)
        return self._client.presigned_get_object(self._bucket, object_key, expires=expires)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ref_to_key(self, payload_ref: str) -> str:
        """Extract the object key from ``s3://<bucket>/<key>``."""
        prefix = f"s3://{self._bucket}/"
        if not payload_ref.startswith(prefix):
            raise ValueError(f"payload_ref {payload_ref!r} does not match bucket {self._bucket!r}")
        return payload_ref[len(prefix) :]

    @staticmethod
    def _detect_content_type(filename: str) -> str:
        ct, _ = mimetypes.guess_type(filename)
        return ct or "application/octet-stream"

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        """Return the hex-encoded SHA-256 digest of *data*."""
        return hashlib.sha256(data).hexdigest()
