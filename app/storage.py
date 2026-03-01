from __future__ import annotations

from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from app.config import Settings


class ObjectStorageClient(Protocol):
    def put_file(self, key: str, source_path: Path) -> None:
        ...

    def put_bytes(self, key: str, payload: bytes) -> None:
        ...

    def get_bytes(self, key: str) -> bytes:
        ...

    def delete(self, key: str) -> None:
        ...


class LocalObjectStorageClient:
    def __init__(self, base_path: str):
        self._base_path = Path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    def put_file(self, key: str, source_path: Path) -> None:
        destination = self._path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_path.read_bytes())

    def put_bytes(self, key: str, payload: bytes) -> None:
        destination = self._path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    def get_bytes(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    def _path_for(self, key: str) -> Path:
        return self._base_path / key


class S3ObjectStorageClient:
    def __init__(self, settings: Settings):
        session = boto3.session.Session()
        self._bucket = settings.s3_bucket_name
        self._client = session.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        self._ensure_bucket()

    def put_file(self, key: str, source_path: Path) -> None:
        with source_path.open("rb") as handle:
            self._client.upload_fileobj(handle, self._bucket, key)

    def put_bytes(self, key: str, payload: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=payload)

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)


def build_storage_client(settings: Settings) -> ObjectStorageClient:
    if settings.storage_backend == "local":
        return LocalObjectStorageClient(settings.local_storage_path)
    return S3ObjectStorageClient(settings)
