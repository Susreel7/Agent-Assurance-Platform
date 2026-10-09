"""Dataset and immutable revision business logic."""

from __future__ import annotations

import csv
import io
import json
from typing import Any
from uuid import UUID

from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.errors import ConflictError, NotFoundError, PayloadTooLargeError, ValidationError
from evaluate.providers.encryption.factory import get_encryption_provider
from evaluate.util import digest_json


def _metadata_size_ok(settings: Settings, metadata: dict[str, Any]) -> None:
    raw = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    if len(raw) > settings.inline_metadata_max_bytes:
        raise PayloadTooLargeError("example metadata exceeds inline limit")


def _inline_or_encrypt(
    settings: Settings,
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, bytes | None, str | None, bool]:
    if payload is None:
        return None, None, None, False
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(raw) <= settings.inline_content_max_bytes:
        return payload, None, None, False
    provider = get_encryption_provider(settings, settings.default_encryption_key_ref)
    cipher = provider.encrypt(raw)
    return None, cipher, settings.default_encryption_key_ref, True


def create_dataset(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    display_name: str,
    description: str,
    tags: list[str],
    actor: str,
) -> dict[str, Any]:
    existing = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    if existing:
        raise ConflictError("dataset already exists")
    repo.insert_dataset(
        conn,
        org_id=org_id,
        project_id=project_id,
        dataset_key=dataset_key,
        display_name=display_name,
        description=description,
        tags=tags,
        actor=actor,
    )
    row = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    assert row is not None
    return row


def create_revision(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    payload_examples: list[dict[str, Any]],
    copy_from_revision_id: UUID | None,
    actor: str,
) -> dict[str, Any]:
    ds = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    if not ds:
        raise NotFoundError("dataset not found")
    dataset_id = ds["id"]
    rev_num = repo.latest_dataset_revision_number(conn, dataset_id) + 1
    manifest: list[dict[str, Any]] = []
    ordinal = 0

    if copy_from_revision_id:
        prior = repo.get_dataset_revision(conn, org_id, copy_from_revision_id)
        if not prior or prior["dataset_id"] != dataset_id:
            raise NotFoundError("copy_from revision not found")
        for ex in repo.list_examples_for_revision(conn, org_id, copy_from_revision_id):
            manifest.append({"example_key": ex["example_key"], "digest": ex["content_digest"]})

    rev_id = repo.insert_dataset_revision(
        conn,
        dataset_id=dataset_id,
        org_id=org_id,
        project_id=project_id,
        revision_number=rev_num,
        manifest_digest="pending",
        actor=actor,
    )

    if copy_from_revision_id:
        for ex in repo.list_examples_for_revision(conn, org_id, copy_from_revision_id):
            ordinal += 1
            inp = ex.get("input_inline")
            ref = ex.get("reference_output_inline")
            cipher = repo.get_example_ciphertext(conn, org_id, ex["id"])
            repo.insert_example(
                conn,
                revision_id=rev_id,
                org_id=org_id,
                project_id=project_id,
                example_key=ex["example_key"],
                ordinal=ordinal,
                split_name=ex["split_name"],
                tags=ex["tags"] if isinstance(ex["tags"], list) else json.loads(ex["tags"]),
                metadata=ex["metadata"]
                if isinstance(ex["metadata"], dict)
                else json.loads(ex["metadata"]),
                content_digest=ex["content_digest"],
                source_trace_id=ex.get("source_trace_id"),
                dedupe_digest=ex.get("dedupe_digest"),
                has_encrypted_payload=bool(ex.get("has_encrypted_payload")),
                input_inline=inp if isinstance(inp, dict) else None,
                reference_inline=ref if isinstance(ref, dict) else None,
                ciphertext=cipher,
                encryption_key_ref=ex.get("encryption_key_ref"),
                input_object_ref=ex.get("input_object_ref"),
                reference_object_ref=ex.get("reference_output_object_ref"),
            )

    for item in payload_examples:
        ordinal += 1
        meta = item.get("metadata") or {}
        _metadata_size_ok(settings, meta)
        inp_inline, cipher, key_ref, encrypted = _inline_or_encrypt(settings, item.get("input"))
        ref_inline, _, _, _ = _inline_or_encrypt(settings, item.get("reference_output"))
        digest = digest_json(
            {
                "input": item.get("input"),
                "reference": item.get("reference_output"),
                "key": item["example_key"],
            }
        )
        manifest.append({"example_key": item["example_key"], "digest": digest})
        repo.insert_example(
            conn,
            revision_id=rev_id,
            org_id=org_id,
            project_id=project_id,
            example_key=item["example_key"],
            ordinal=ordinal,
            split_name=item.get("split_name", "default"),
            tags=item.get("tags") or [],
            metadata=meta,
            content_digest=digest,
            source_trace_id=item.get("source_trace_id"),
            dedupe_digest=digest,
            has_encrypted_payload=encrypted,
            input_inline=inp_inline,
            reference_inline=ref_inline,
            ciphertext=cipher,
            encryption_key_ref=key_ref,
            input_object_ref=None,
            reference_object_ref=None,
        )

    manifest_digest = digest_json(manifest)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.dataset_revisions SET manifest_digest = %s WHERE id = %s
            """,
            (manifest_digest, rev_id),
        )
    row = repo.get_dataset_revision(conn, org_id, rev_id)
    assert row is not None
    return row


def import_jsonl(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    content: str,
    actor: str,
) -> dict[str, Any]:
    examples: list[dict[str, Any]] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"invalid JSONL at line {line_no}") from exc
        if not isinstance(obj, dict):
            raise ValidationError(f"JSONL line {line_no} must be object")
        key = obj.get("example_key") or obj.get("id") or f"row-{line_no}"
        examples.append(
            {
                "example_key": str(key),
                "input": obj.get("input", obj),
                "reference_output": obj.get("reference_output"),
                "split_name": obj.get("split", "default"),
                "tags": obj.get("tags") or [],
                "metadata": obj.get("metadata") or {},
            }
        )
    return create_revision(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        dataset_key=dataset_key,
        payload_examples=examples,
        copy_from_revision_id=None,
        actor=actor,
    )


def import_csv(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    content: str,
    actor: str,
) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(content))
    examples: list[dict[str, Any]] = []
    for line_no, row in enumerate(reader, start=2):
        if not row:
            continue
        key = row.get("example_key") or row.get("id") or f"row-{line_no}"
        inp_raw = row.get("input") or "{}"
        ref_raw = row.get("reference_output")
        try:
            inp = json.loads(inp_raw) if inp_raw else {}
        except json.JSONDecodeError as exc:
            raise ValidationError(f"invalid input JSON at CSV line {line_no}") from exc
        ref = None
        if ref_raw:
            try:
                ref = json.loads(ref_raw)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"invalid reference_output JSON at CSV line {line_no}"
                ) from exc
        examples.append(
            {
                "example_key": str(key),
                "input": inp,
                "reference_output": ref,
                "split_name": row.get("split") or "default",
                "tags": [],
                "metadata": {},
            }
        )
    return create_revision(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        dataset_key=dataset_key,
        payload_examples=examples,
        copy_from_revision_id=None,
        actor=actor,
    )


def export_revision_jsonl(conn: PgConn, org_id: UUID, revision_id: UUID) -> str:
    rev = repo.get_dataset_revision(conn, org_id, revision_id)
    if not rev:
        raise NotFoundError("revision not found")
    lines: list[str] = []
    for ex in repo.list_examples_for_revision(conn, org_id, revision_id):
        record = {
            "example_key": ex["example_key"],
            "split": ex["split_name"],
            "tags": ex["tags"],
            "metadata": ex["metadata"],
            "input": ex.get("input_inline"),
            "reference_output": ex.get("reference_output_inline"),
        }
        lines.append(json.dumps(record, separators=(",", ":")))
    return "\n".join(lines) + ("\n" if lines else "")


def export_revision_csv(conn: PgConn, org_id: UUID, revision_id: UUID) -> str:
    rev = repo.get_dataset_revision(conn, org_id, revision_id)
    if not rev:
        raise NotFoundError("revision not found")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["example_key", "split", "input", "reference_output"])
    writer.writeheader()
    for ex in repo.list_examples_for_revision(conn, org_id, revision_id):
        writer.writerow(
            {
                "example_key": ex["example_key"],
                "split": ex["split_name"],
                "input": json.dumps(ex.get("input_inline")),
                "reference_output": json.dumps(ex.get("reference_output_inline")),
            }
        )
    return buf.getvalue()
