"""Azure Blob object store."""

from __future__ import annotations

from evaluate.config import Settings
from evaluate.errors import NotFoundError, ValidationError
from evaluate.providers.object_store.base import ObjectStoreProvider, StoredObject


class AzureObjectStore(ObjectStoreProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.object_store_azure_container or not settings.object_store_azure_account_url:
            raise ValidationError("Azure object store requires container and account URL")
        try:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:
            raise ValidationError("azure-storage-blob required for azure backend") from exc
        self._container = settings.object_store_azure_container
        credential = DefaultAzureCredential()
        self._client = BlobServiceClient(
            account_url=settings.object_store_azure_account_url.rstrip("/"),
            credential=credential,
        )

    def _blob_name(self, org_id: str, project_id: str, purpose: str, object_id: str) -> str:
        return f"{org_id}/{project_id}/{purpose}/{object_id}"

    def put(
        self,
        *,
        org_id: str,
        project_id: str,
        purpose: str,
        object_id: str,
        data: bytes,
    ) -> StoredObject:
        name = self._blob_name(org_id, project_id, purpose, object_id)
        blob = self._client.get_blob_client(container=self._container, blob=name)
        blob.upload_blob(data, overwrite=True)
        return StoredObject(
            storage_ref=f"azure:{self._container}/{name}",
            size_bytes=len(data),
        )

    def get(self, storage_ref: str) -> bytes:
        if not storage_ref.startswith("azure:"):
            raise ValueError("invalid azure ref")
        _, rest = storage_ref.split(":", 1)
        container, name = rest.split("/", 1)
        blob = self._client.get_blob_client(container=container, blob=name)
        try:
            data = blob.download_blob().readall()
        except Exception as exc:
            raise NotFoundError("object not found") from exc
        return bytes(data)

    def delete(self, storage_ref: str) -> None:
        if not storage_ref.startswith("azure:"):
            return
        _, rest = storage_ref.split(":", 1)
        container, name = rest.split("/", 1)
        blob = self._client.get_blob_client(container=container, blob=name)
        blob.delete_blob()
