"""Signed download metadata for attachment access."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from uuid import UUID

from evaluate.config import Settings


def sign_download(
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    object_ref_id: UUID,
) -> dict[str, Any]:
    expires = int(time.time()) + settings.download_url_ttl_seconds
    payload = f"{org_id}:{project_id}:{object_ref_id}:{expires}"
    sig = hmac.new(
        settings.download_signing_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "object_ref_id": str(object_ref_id),
        "expires_at": expires,
        "signature": sig,
    }


def verify_download_signature(
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    object_ref_id: UUID,
    expires_at: int,
    signature: str,
) -> bool:
    if expires_at < int(time.time()):
        return False
    payload = f"{org_id}:{project_id}:{object_ref_id}:{expires_at}"
    expected = hmac.new(
        settings.download_signing_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
