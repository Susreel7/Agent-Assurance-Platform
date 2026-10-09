"""Request size and span count limits."""

from __future__ import annotations

import gzip

from observe.config import Settings
from observe.errors import InvalidEnvelopeError, PayloadTooLargeError


def decompress_if_needed(body: bytes, content_encoding: str | None, settings: Settings) -> bytes:
    if len(body) > settings.max_compressed_bytes:
        raise PayloadTooLargeError("compressed body exceeds limit")
    enc = (content_encoding or "identity").strip().lower()
    if enc == "identity":
        if len(body) > settings.max_uncompressed_bytes:
            raise PayloadTooLargeError("uncompressed body exceeds limit")
        return body
    if enc == "gzip":
        try:
            raw = gzip.decompress(body)
        except OSError as exc:
            raise InvalidEnvelopeError("gzip decompression failed") from exc
        if len(raw) > settings.max_uncompressed_bytes:
            raise PayloadTooLargeError("uncompressed body exceeds limit")
        return raw
    raise InvalidEnvelopeError(f"unsupported content encoding: {enc}")
