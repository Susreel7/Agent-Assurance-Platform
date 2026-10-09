"""Encrypted dataset attachment storage."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.errors import NotFoundError
from evaluate.providers.download_sign import sign_download
from evaluate.providers.encryption.factory import get_encryption_provider
from evaluate.providers.object_store.factory import get_object_store
from evaluate.util import digest_json


def store_attachment(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    purpose: str,
    plaintext: bytes,
    mime_type: str,
    encryption_key_ref: str | None = None,
) -> UUID:
    key_ref = encryption_key_ref or settings.default_encryption_key_ref
    provider = get_encryption_provider(settings, key_ref)
    ciphertext = provider.encrypt(plaintext)
    digest = digest_json({"size": len(plaintext), "digest": digest_json({"len": len(ciphertext)})})
    store = get_object_store(settings)
    object_id = str(uuid.uuid4())
    stored = store.put(
        org_id=str(org_id),
        project_id=str(project_id),
        purpose=purpose,
        object_id=object_id,
        data=ciphertext,
    )
    return repo.insert_object_ref(
        conn,
        org_id=org_id,
        project_id=project_id,
        purpose=purpose,
        storage_ref=stored.storage_ref,
        encryption_key_ref=key_ref,
        content_digest=digest,
        size_bytes=stored.size_bytes,
        mime_type=mime_type,
    )


def load_attachment_bytes(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    ref_id: UUID,
) -> bytes:
    row = repo.get_object_ref(conn, org_id, project_id, ref_id)
    if not row:
        raise NotFoundError("attachment not found")
    store = get_object_store(settings)
    ciphertext = store.get(str(row["storage_ref"]))
    provider = get_encryption_provider(settings, str(row["encryption_key_ref"]))
    return provider.decrypt(ciphertext)


def load_inline_payload(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    storage_ref: str,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.object_refs
            WHERE organization_id = %s AND project_id = %s AND storage_ref = %s
            """,
            (org_id, project_id, storage_ref),
        )
        row = cur.fetchone()
    if not row:
        raise NotFoundError("object ref not found")
    raw = load_attachment_bytes(
        conn, settings, org_id=org_id, project_id=project_id, ref_id=row["id"]
    )
    parsed = json.loads(raw.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def signed_download_metadata(
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    ref_id: UUID,
) -> dict[str, Any]:
    return sign_download(settings, org_id=org_id, project_id=project_id, object_ref_id=ref_id)
