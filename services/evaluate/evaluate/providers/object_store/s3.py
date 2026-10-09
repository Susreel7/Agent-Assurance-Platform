"""S3-compatible object store."""

from __future__ import annotations

from evaluate.config import Settings
from evaluate.errors import NotFoundError, ValidationError
from evaluate.providers.object_store.base import ObjectStoreProvider, StoredObject


class S3ObjectStore(ObjectStoreProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.object_store_s3_bucket:
            raise ValidationError("EVALUATE_OBJECT_STORE_S3_BUCKET is required for s3 backend")
        try:
            import boto3
        except ImportError as exc:
            raise ValidationError("boto3 required for s3 object store") from exc
        self._bucket = settings.object_store_s3_bucket
        self._prefix = settings.object_store_s3_prefix.strip("/")
        self._client = boto3.client("s3", region_name=settings.object_store_s3_region or None)

    def _key(self, org_id: str, project_id: str, purpose: str, object_id: str) -> str:
        base = f"{org_id}/{project_id}/{purpose}/{object_id}"
        return f"{self._prefix}/{base}" if self._prefix else base

    def put(
        self,
        *,
        org_id: str,
        project_id: str,
        purpose: str,
        object_id: str,
        data: bytes,
    ) -> StoredObject:
        key = self._key(org_id, project_id, purpose, object_id)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return StoredObject(storage_ref=f"s3:{self._bucket}/{key}", size_bytes=len(data))

    def get(self, storage_ref: str) -> bytes:
        if not storage_ref.startswith("s3:"):
            raise ValueError("invalid s3 ref")
        _, bucket_key = storage_ref.split(":", 1)
        bucket, key = bucket_key.split("/", 1)
        try:
            resp = self._client.get_object(Bucket=bucket, Key=key)
        except Exception as exc:
            err_name = exc.__class__.__name__
            if "NoSuchKey" in err_name or "404" in str(exc):
                raise NotFoundError("object not found") from exc
            raise
        body = resp["Body"].read()
        return bytes(body)

    def delete(self, storage_ref: str) -> None:
        if not storage_ref.startswith("s3:"):
            return
        _, bucket_key = storage_ref.split(":", 1)
        bucket, key = bucket_key.split("/", 1)
        self._client.delete_object(Bucket=bucket, Key=key)
