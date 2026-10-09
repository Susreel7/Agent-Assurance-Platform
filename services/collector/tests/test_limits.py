from __future__ import annotations

import gzip

import pytest

from collector.config import Settings
from collector.errors import PayloadTooLargeError
from collector.limits import decompress_if_needed


def test_gzip_roundtrip() -> None:
    raw = b"x" * 50
    body = gzip.compress(raw)
    settings = Settings(max_compressed_bytes=10_000, max_uncompressed_bytes=10_000)
    assert decompress_if_needed(body, "gzip", settings) == raw


def test_compressed_limit() -> None:
    settings = Settings(max_compressed_bytes=10, max_uncompressed_bytes=1000)
    with pytest.raises(PayloadTooLargeError):
        decompress_if_needed(b"x" * 20, "identity", settings)
