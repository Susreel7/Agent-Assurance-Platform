"""Google Cloud Storage object store."""

from __future__ import annotations

from datetime import timedelta

from observe.providers.object_store.base import ObjectStore, StoredObject


class GCSObjectStore(ObjectStore):
    def __init__(self, *, bucket: str, prefix: str = "") -> None:
        if not bucket:
            raise ValueError("OBSERVE_OBJECT_STORE_BUCKET is required for GCS")
        from google.cloud import storage

        self._bucket_name = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)

    def _blob_name(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        blob = self._bucket.blob(self._blob_name(key))
        blob.upload_from_string(data, content_type=content_type)
        return StoredObject(
            key=key,
            digest=self.digest(data),
            size=len(data),
            uri=f"gs://{self._bucket_name}/{self._blob_name(key)}",
            encryption="gcs:google-managed",
        )

    def get(self, key: str) -> bytes:
        blob = self._bucket.blob(self._blob_name(key))
        return bytes(blob.download_as_bytes())

    def exists(self, key: str) -> bool:
        blob = self._bucket.blob(self._blob_name(key))
        return bool(blob.exists())

    def delete(self, key: str) -> None:
        blob = self._bucket.blob(self._blob_name(key))
        if blob.exists():
            blob.delete()

    def presign(self, key: str, expires: timedelta) -> str:
        blob = self._bucket.blob(self._blob_name(key))
        return str(blob.generate_signed_url(expiration=expires, method="GET"))
