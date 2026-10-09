from __future__ import annotations

import gzip

import pytest

from observe.config import Settings
from observe.errors import PayloadTooLargeError
from observe.ingest.limits import decompress_if_needed


def test_gzip_decompress_within_limits() -> None:
    raw = b"x" * 100
    body = gzip.compress(raw)
    settings = Settings(max_uncompressed_bytes=1000, max_compressed_bytes=1000)
    out = decompress_if_needed(body, "gzip", settings)
    assert out == raw


def test_compressed_limit_enforced() -> None:
    settings = Settings(max_compressed_bytes=10, max_uncompressed_bytes=1000)
    with pytest.raises(PayloadTooLargeError):
        decompress_if_needed(b"x" * 20, "identity", settings)
