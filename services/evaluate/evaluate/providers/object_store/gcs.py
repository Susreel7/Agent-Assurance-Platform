"""Google Cloud Storage object store."""

from __future__ import annotations

from evaluate.config import Settings
from evaluate.errors import NotFoundError, ValidationError
from evaluate.providers.object_store.base import ObjectStoreProvider, StoredObject


class GcsObjectStore(ObjectStoreProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.object_store_gcs_bucket:
            raise ValidationError("EVALUATE_OBJECT_STORE_GCS_BUCKET required for gcs backend")
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise ValidationError("google-cloud-storage required for gcs backend") from exc
        self._client = storage.Client()
        self._bucket = self._client.bucket(settings.object_store_gcs_bucket)
        self._prefix = settings.object_store_gcs_prefix.strip("/")

    def _name(self, org_id: str, project_id: str, purpose: str, object_id: str) -> str:
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
        name = self._name(org_id, project_id, purpose, object_id)
        blob = self._bucket.blob(name)
        blob.upload_from_string(data)
        return StoredObject(storage_ref=f"gcs:{self._bucket.name}/{name}", size_bytes=len(data))

    def get(self, storage_ref: str) -> bytes:
        if not storage_ref.startswith("gcs:"):
            raise ValueError("invalid gcs ref")
        _, rest = storage_ref.split(":", 1)
        bucket_name, name = rest.split("/", 1)
        bucket = self._client.bucket(bucket_name)
        blob = bucket.blob(name)
        if not blob.exists():
            raise NotFoundError("object not found")
        return bytes(blob.download_as_bytes())

    def delete(self, storage_ref: str) -> None:
        if not storage_ref.startswith("gcs:"):
            return
        _, rest = storage_ref.split(":", 1)
        bucket_name, name = rest.split("/", 1)
        bucket = self._client.bucket(bucket_name)
        bucket.blob(name).delete()
