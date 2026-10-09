from __future__ import annotations

from pathlib import Path

import pytest

from observe.config import ObjectStoreKind, Settings
from observe.errors import UnsupportedProviderError
from observe.providers.object_store.factory import build_object_store


def test_local_object_store_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    settings = Settings(object_store=ObjectStoreKind.LOCAL, object_store_root=str(root))
    store = build_object_store(settings)
    obj = store.put("org/proj/x.bin", b"hello", "application/octet-stream")
    assert store.get("org/proj/x.bin") == b"hello"
    assert obj.digest.startswith("sha256:")


def test_s3_not_implemented() -> None:
    settings = Settings(object_store=ObjectStoreKind.S3, object_store_bucket="b")
    with pytest.raises(UnsupportedProviderError):
        build_object_store(settings)
