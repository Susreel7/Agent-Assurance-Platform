from __future__ import annotations

import pytest

from observe.config import ObjectStoreKind, Settings
from observe.errors import UnsupportedProviderError
from observe.providers.object_store.factory import build_object_store


def test_s3_requires_bucket() -> None:
    settings = Settings(object_store=ObjectStoreKind.S3, object_store_bucket="")
    with pytest.raises(UnsupportedProviderError):
        build_object_store(settings)
