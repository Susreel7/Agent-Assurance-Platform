"""Capture mode handling — never put raw content in ClickHouse."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from observe.config import CaptureMode, Settings
from observe.errors import ObserveError
from observe.providers.object_store.base import ObjectStore, tenant_payload_key
from observe.providers.object_store.encrypted import PayloadCipher
from observe.worker.normalizer import NormalizedSpan


@dataclass(frozen=True, slots=True)
class PayloadWrite:
    field_name: str
    digest: str
    object_key: str
    media_type: str
    byte_size: int
    retention_deadline: datetime
    encryption_key_ref: str
    legal_hold: bool = False


def _hash_only(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _redact_preview(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[:max_bytes].decode("utf-8", errors="ignore") + "…"


def process_capture_for_manifest(
    settings: Settings,
    store: ObjectStore,
    *,
    org_id: UUID,
    project_id: UUID,
    mode: CaptureMode,
    encryption_key_ref: str | None,
    retention_days: int,
    ns: NormalizedSpan,
) -> list[PayloadWrite]:
    if ns.payload_preprocessed or mode == CaptureMode.NONE or not ns.payload_fields:
        return []

    key_ref = encryption_key_ref or "local:fernet"
    retention_deadline = datetime.now(UTC) + timedelta(days=retention_days)
    writes: list[PayloadWrite] = []

    if mode == CaptureMode.DIGEST:
        for field_name, content in ns.payload_fields.items():
            raw = json.dumps(content, default=str).encode("utf-8")
            digest = _hash_only(raw)
            writes.append(
                PayloadWrite(
                    field_name=field_name,
                    digest=digest,
                    object_key="",
                    media_type="application/digest",
                    byte_size=len(raw),
                    retention_deadline=retention_deadline,
                    encryption_key_ref=key_ref,
                )
            )
        return writes

    if not settings.payload_encryption_key:
        raise ObserveError(
            "OBSERVE_PAYLOAD_ENCRYPTION_KEY required for redacted/full capture",
            code="payload_encryption_required",
        )
    cipher = PayloadCipher(settings.payload_encryption_key)

    for field_name, content in ns.payload_fields.items():
        if isinstance(content, str) and content.startswith("ref:"):
            continue
        if mode == CaptureMode.REDACTED:
            plaintext = _redact_preview(str(content), settings.redacted_preview_max_bytes).encode(
                "utf-8"
            )
            media = "application/json+redacted"
        else:
            plaintext = json.dumps(content, default=str).encode("utf-8")
            media = "application/octet-stream"
        digest = store.digest(plaintext)
        object_key = tenant_payload_key(org_id, project_id, digest)
        if not store.exists(object_key):
            store.put(object_key, cipher.encrypt(plaintext), media)
        writes.append(
            PayloadWrite(
                field_name=field_name,
                digest=digest,
                object_key=object_key,
                media_type=media,
                byte_size=len(plaintext),
                retention_deadline=retention_deadline,
                encryption_key_ref=key_ref,
            )
        )
    return writes
