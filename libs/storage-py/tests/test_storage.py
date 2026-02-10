"""Tests for orchestack-storage using moto S3 mock."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from orchestack_storage.client import BUCKET_ARTIFACTS, ChecksumMismatchError, StorageClient
from orchestack_storage.config import StorageConfig

TEST_CONFIG = StorageConfig(
    endpoint="http://localhost:5555",
    access_key="testing",
    secret_key="testing",
    region="us-east-1",
    use_ssl=False,
)


@pytest.fixture
def s3_mock():
    """Provide a moto-mocked S3 environment with a test bucket."""
    with mock_aws():
        conn = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        conn.create_bucket(Bucket=BUCKET_ARTIFACTS)
        yield conn


@pytest.fixture
def client(s3_mock):
    """Return a StorageClient wired to the moto mock."""
    c = StorageClient(TEST_CONFIG)
    # Replace the internal boto client with the mocked one.
    c._s3 = s3_mock
    return c


class TestPutObject:
    def test_returns_payload_ref_and_sha256(self, client: StorageClient):
        result = client.put_object(BUCKET_ARTIFACTS, "test/hello.txt", b"hello world")
        assert result["payload_ref"] == f"s3://{BUCKET_ARTIFACTS}/test/hello.txt"
        assert len(result["sha256"]) == 64
        assert result["size"] == 11

    def test_accepts_string_data(self, client: StorageClient):
        result = client.put_object(BUCKET_ARTIFACTS, "test/str.txt", "string data")
        assert result["size"] == 11


class TestGetObject:
    def test_roundtrip(self, client: StorageClient):
        data = b"roundtrip test data"
        client.put_object(BUCKET_ARTIFACTS, "rt.bin", data)
        fetched = client.get_object(BUCKET_ARTIFACTS, "rt.bin")
        assert fetched == data

    def test_checksum_verification_passes(self, client: StorageClient):
        data = b"verified data"
        put_result = client.put_object(BUCKET_ARTIFACTS, "verified.bin", data)
        fetched = client.get_object(BUCKET_ARTIFACTS, "verified.bin", expected_sha256=put_result["sha256"])
        assert fetched == data

    def test_checksum_verification_fails(self, client: StorageClient):
        client.put_object(BUCKET_ARTIFACTS, "bad.bin", b"data")
        with pytest.raises(ChecksumMismatchError):
            client.get_object(BUCKET_ARTIFACTS, "bad.bin", expected_sha256="0" * 64)


class TestListObjects:
    def test_list_empty(self, client: StorageClient):
        result = client.list_objects(BUCKET_ARTIFACTS)
        assert result == []

    def test_list_with_prefix(self, client: StorageClient):
        client.put_object(BUCKET_ARTIFACTS, "a/1.txt", b"one")
        client.put_object(BUCKET_ARTIFACTS, "a/2.txt", b"two")
        client.put_object(BUCKET_ARTIFACTS, "b/3.txt", b"three")

        result = client.list_objects(BUCKET_ARTIFACTS, prefix="a/")
        assert len(result) == 2
        keys = {r["key"] for r in result}
        assert keys == {"a/1.txt", "a/2.txt"}


class TestDeleteObject:
    def test_delete(self, client: StorageClient):
        client.put_object(BUCKET_ARTIFACTS, "del.txt", b"delete me")
        client.delete_object(BUCKET_ARTIFACTS, "del.txt")
        result = client.list_objects(BUCKET_ARTIFACTS)
        assert len(result) == 0


class TestHeadObject:
    def test_head(self, client: StorageClient):
        client.put_object(BUCKET_ARTIFACTS, "head.txt", b"head test", content_type="text/plain")
        meta = client.head_object(BUCKET_ARTIFACTS, "head.txt")
        assert meta["payload_ref"] == f"s3://{BUCKET_ARTIFACTS}/head.txt"
        assert meta["size"] == 9
        assert meta["content_type"] == "text/plain"


class TestPayloadRef:
    def test_static_method(self):
        ref = StorageClient.payload_ref("my-bucket", "path/to/file.json")
        assert ref == "s3://my-bucket/path/to/file.json"


class TestConfig:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MINIO_ENDPOINT", "storage.example.com:9000")
        monkeypatch.setenv("MINIO_ACCESS_KEY", "mykey")
        monkeypatch.setenv("MINIO_SECRET_KEY", "mysecret")
        monkeypatch.setenv("MINIO_REGION", "eu-west-1")

        cfg = StorageConfig.from_env()
        assert cfg.endpoint == "http://storage.example.com:9000"
        assert cfg.access_key == "mykey"
        assert cfg.secret_key == "mysecret"
        assert cfg.region == "eu-west-1"
        assert cfg.use_ssl is False

    def test_from_env_with_ssl(self, monkeypatch):
        monkeypatch.setenv("MINIO_ENDPOINT", "secure.example.com:9000")
        monkeypatch.setenv("MINIO_USE_SSL", "true")

        cfg = StorageConfig.from_env()
        assert cfg.endpoint == "https://secure.example.com:9000"
        assert cfg.use_ssl is True
