"""Object store factory."""

from __future__ import annotations

from evaluate.config import Settings
from evaluate.errors import ValidationError
from evaluate.providers.object_store.azure import AzureObjectStore
from evaluate.providers.object_store.base import ObjectStoreProvider
from evaluate.providers.object_store.gcs import GcsObjectStore
from evaluate.providers.object_store.local import LocalObjectStore
from evaluate.providers.object_store.s3 import S3ObjectStore


def get_object_store(settings: Settings) -> ObjectStoreProvider:
    backend = settings.object_store_backend
    if backend == "local":
        return LocalObjectStore(settings.object_store_local_root)
    if backend == "s3":
        return S3ObjectStore(settings)
    if backend == "azure":
        return AzureObjectStore(settings)
    if backend == "gcs":
        return GcsObjectStore(settings)
    raise ValidationError(f"unsupported object store backend: {backend}")
