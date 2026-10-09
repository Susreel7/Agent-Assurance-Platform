"""Azure Blob object store."""

from __future__ import annotations

from datetime import timedelta

from observe.providers.object_store.base import ObjectStore, StoredObject


class AzureBlobObjectStore(ObjectStore):
    def __init__(self, *, account_url: str, container: str, prefix: str = "") -> None:
        if not container:
            raise ValueError("OBSERVE_OBJECT_STORE_BUCKET (container) is required for Azure")
        from azure.storage.blob import BlobServiceClient

        self._container = container
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._client = BlobServiceClient(account_url=account_url).get_container_client(container)

    def _blob(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        blob = self._client.get_blob_client(self._blob(key))
        blob.upload_blob(data, overwrite=True, content_type=content_type)
        return StoredObject(
            key=key,
            digest=self.digest(data),
            size=len(data),
            uri=f"azure://{self._container}/{self._blob(key)}",
            encryption="azure:service",
        )

    def get(self, key: str) -> bytes:
        blob = self._client.get_blob_client(self._blob(key))
        return bytes(blob.download_blob().readall())

    def exists(self, key: str) -> bool:
        blob = self._client.get_blob_client(self._blob(key))
        return bool(blob.exists())

    def delete(self, key: str) -> None:
        blob = self._client.get_blob_client(self._blob(key))
        if blob.exists():
            blob.delete_blob(delete_snapshots="include")

    def presign(self, key: str, expires: timedelta) -> str:
        _ = expires
        return f"/v1/observe/objects/azure/{self._blob(key)}"
