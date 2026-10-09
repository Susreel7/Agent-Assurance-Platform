"""Construct object store from settings."""

from __future__ import annotations

from pathlib import Path

from observe.config import ObjectStoreKind, Settings
from observe.errors import UnsupportedProviderError
from observe.providers.object_store.base import LocalObjectStore, ObjectStore


def build_object_store(settings: Settings) -> ObjectStore:
    kind = settings.object_store
    if kind == ObjectStoreKind.LOCAL:
        return LocalObjectStore(Path(settings.object_store_root))

    if kind == ObjectStoreKind.S3:
        try:
            from observe.providers.object_store.s3 import S3ObjectStore
        except ImportError as exc:
            raise UnsupportedProviderError(
                "Install aap-observe[aws] for S3 object store",
                code="s3_extra_missing",
            ) from exc
        if not settings.object_store_bucket:
            raise UnsupportedProviderError(
                "OBSERVE_OBJECT_STORE_BUCKET is required for S3",
                code="s3_config_invalid",
            )
        try:
            return S3ObjectStore(
                bucket=settings.object_store_bucket,
                prefix=settings.object_store_prefix,
                endpoint=settings.s3_endpoint or None,
                region=settings.s3_region or None,
                kms_key_id=settings.s3_kms_key_id or None,
            )
        except ImportError as exc:
            raise UnsupportedProviderError(
                "Install aap-observe[aws] for S3 object store",
                code="s3_extra_missing",
            ) from exc

    if kind == ObjectStoreKind.AZURE:
        try:
            from observe.providers.object_store.azure_store import AzureBlobObjectStore
        except ImportError as exc:
            raise UnsupportedProviderError(
                "Install aap-observe[azure] for Azure object store",
                code="azure_extra_missing",
            ) from exc
        if not settings.azure_storage_account_url:
            raise UnsupportedProviderError(
                "OBSERVE_AZURE_STORAGE_ACCOUNT_URL is required for Azure",
                code="azure_config_invalid",
            )
        return AzureBlobObjectStore(
            account_url=settings.azure_storage_account_url,
            container=settings.object_store_bucket,
            prefix=settings.object_store_prefix,
        )

    if kind == ObjectStoreKind.GCS:
        try:
            from observe.providers.object_store.gcs import GCSObjectStore
        except ImportError as exc:
            raise UnsupportedProviderError(
                "Install aap-observe[gcp] for GCS object store",
                code="gcs_extra_missing",
            ) from exc
        return GCSObjectStore(
            bucket=settings.object_store_bucket,
            prefix=settings.object_store_prefix,
        )

    raise UnsupportedProviderError(f"unknown object store: {kind!s}")
