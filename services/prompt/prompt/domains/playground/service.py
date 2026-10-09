"""Playground execution against the Go Router."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import httpx

from prompt.auth.schemas import InternalPrincipal
from prompt.config import Settings
from prompt.db import repository as repo
from prompt.db.postgres import PgConn
from prompt.domains.artifacts import service as artifact_service
from prompt.domains.playground.schemas import (
    ArtifactRef,
    PlaygroundRunRequest,
    PlaygroundRunResponse,
)
from prompt.errors import NotFoundError, RouterUpstreamError, ValidationError
from prompt.validation.canonicalize import sha256_hex


def _resolve_ref(
    conn: PgConn,
    settings: Settings,
    org_id: UUID,
    project_id: UUID,
    ref: ArtifactRef,
) -> tuple[UUID, dict[str, Any]]:
    if ref.revision_id is not None:
        detail = artifact_service.copy_revision_for_playground(
            conn, settings, org_id, project_id, ref.revision_id
        )
        return detail.id, detail.content
    if ref.artifact_key and ref.label:
        artifact = repo.get_artifact_by_key(conn, org_id, project_id, ref.artifact_key)
        if artifact is None:
            raise NotFoundError(f"artifact {ref.artifact_key} not found")
        label_row = repo.get_label(conn, org_id, project_id, artifact.id, ref.label.strip().lower())
        if label_row is None:
            raise NotFoundError(f"label {ref.label} not set on {ref.artifact_key}")
        if ref.label.strip().lower() == "production":
            rev = repo.get_revision(conn, org_id, project_id, label_row.revision_id)
            if rev is not None and rev.is_draft:
                raise ValidationError("production label points at draft")
        detail = artifact_service.copy_revision_for_playground(
            conn, settings, org_id, project_id, label_row.revision_id
        )
        return detail.id, detail.content
    raise ValidationError("each artifact ref requires revision_id or artifact_key+label")


def _build_messages(
    resolved_contents: list[dict[str, Any]],
    override: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if override:
        return override
    messages: list[dict[str, Any]] = []
    for content in resolved_contents:
        msgs = content.get("messages")
        if isinstance(msgs, list):
            messages.extend(msgs)
    if not messages:
        raise ValidationError("no messages resolved from artifacts")
    return messages


def _substitute_variables(text: str, variables: dict[str, Any]) -> str:
    out = text
    for key, value in variables.items():
        out = out.replace(f"{{{{ {key} }}}}", str(value)).replace(f"{{{{{key}}}}}", str(value))
    return out


def _apply_variables(
    messages: list[dict[str, Any]], variables: dict[str, Any]
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for msg in messages:
        copy = dict(msg)
        content = copy.get("content")
        if isinstance(content, str):
            copy["content"] = _substitute_variables(content, variables)
        applied.append(copy)
    return applied


async def _call_router(
    settings: Settings,
    *,
    workload_bearer: str | None,
    body: dict[str, Any],
    stream: bool,
) -> tuple[int, dict[str, str], bytes | Any]:
    url = settings.router_base_url.rstrip("/") + settings.router_chat_path
    headers = {"Content-Type": "application/json"}
    if workload_bearer:
        headers["Authorization"] = f"Bearer {workload_bearer}"
    timeout = httpx.Timeout(settings.router_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if stream:
            chunks: list[bytes] = []
            resp_headers: dict[str, str] = {}
            async with client.stream(
                "POST", url, headers=headers, json={**body, "stream": True}
            ) as resp:
                resp_headers = dict(resp.headers)
                status = resp.status_code
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
            return status, resp_headers, b"".join(chunks)
        resp = await client.post(url, headers=headers, json=body)
        return resp.status_code, dict(resp.headers), resp.content


def _prepare_request_body(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    payload: PlaygroundRunRequest,
) -> tuple[list[UUID], dict[str, Any]]:
    if payload.mode == "compare" and len(payload.artifacts) > settings.playground_max_variants:
        raise ValidationError("too many compare variants")
    if payload.stream and payload.mode != "sync":
        raise ValidationError("streaming is only supported for sync playground mode")

    resolved_ids: list[UUID] = []
    resolved_contents: list[dict[str, Any]] = []
    for ref in payload.artifacts:
        rev_id, content = _resolve_ref(conn, settings, org_id, project_id, ref)
        resolved_ids.append(rev_id)
        resolved_contents.append(content)

    messages = _apply_variables(
        _build_messages(resolved_contents, payload.messages_override),
        payload.variables,
    )
    request_body: dict[str, Any] = {
        "model": payload.model_alias,
        "messages": messages,
        **payload.model_settings,
    }
    return resolved_ids, request_body


async def prepare_playground_run(
    conn: PgConn,
    settings: Settings,
    *,
    principal: InternalPrincipal,
    payload: PlaygroundRunRequest,
) -> tuple[UUID, list[UUID], dict[str, Any]]:
    org_id = principal.organization_id
    project_id = principal.project_id
    resolved_ids, request_body = _prepare_request_body(
        conn, settings, org_id=org_id, project_id=project_id, payload=payload
    )
    run_id = repo.insert_playground_run(
        conn,
        org_id=org_id,
        project_id=project_id,
        mode="stream" if payload.stream else payload.mode,
        status="running",
        resolved_revision_ids=resolved_ids,
        model_alias=payload.model_alias,
        variables=payload.variables,
        created_by=principal.actor,
    )
    repo.insert_audit(
        conn,
        org_id=org_id,
        project_id=project_id,
        action="playground.run",
        resource_type="playground_run",
        resource_id=run_id,
        actor=principal.actor,
        detail={
            "mode": payload.mode,
            "stream": payload.stream,
            "resolved_revision_ids": [str(i) for i in resolved_ids],
        },
    )
    return run_id, resolved_ids, request_body


def get_playground_run_status(
    conn: PgConn, org_id: UUID, project_id: UUID, run_id: UUID
) -> dict[str, Any]:
    row = repo.get_playground_run(conn, org_id, project_id, run_id)
    if row is None:
        raise NotFoundError("playground run not found")
    return row


async def cancel_playground_run(
    conn: PgConn,
    settings: Settings,
    org_id: UUID,
    project_id: UUID,
    run_id: UUID,
) -> bool:
    from prompt.domains.playground.cancel_registry import cancel as signal_local_cancel
    from prompt.domains.playground.redis_cancel import publish_cancel

    row = repo.get_playground_run(conn, org_id, project_id, run_id)
    if row is None:
        raise NotFoundError("playground run not found")
    status = str(row.get("status") or "")
    if status not in {"running", "pending", "cancel_requested"}:
        return False

    repo.update_playground_run_status(
        conn,
        org_id=org_id,
        project_id=project_id,
        run_id=run_id,
        status="cancel_requested",
        error_message="cancel requested",
    )
    await publish_cancel(settings, run_id)
    await signal_local_cancel(run_id)
    return True


async def run_playground(
    conn: PgConn,
    settings: Settings,
    *,
    principal: InternalPrincipal,
    payload: PlaygroundRunRequest,
    workload_bearer: str | None,
) -> PlaygroundRunResponse:
    if payload.stream:
        raise ValidationError("use streaming response path when stream=true")

    org_id = principal.organization_id
    project_id = principal.project_id

    resolved_ids, request_body = _prepare_request_body(
        conn, settings, org_id=org_id, project_id=project_id, payload=payload
    )
    input_digest = sha256_hex(json.dumps(request_body, sort_keys=True).encode("utf-8"))

    run_id = repo.insert_playground_run(
        conn,
        org_id=org_id,
        project_id=project_id,
        mode=payload.mode,
        status="running",
        resolved_revision_ids=resolved_ids,
        model_alias=payload.model_alias,
        variables=payload.variables,
        created_by=principal.actor,
    )

    router_trace: dict[str, Any] = {}
    router_request_id: str | None = None
    output: dict[str, Any] | None = None
    error_message: str | None = None
    final_status = "completed"

    try:
        if payload.mode == "compare":
            sem = asyncio.Semaphore(settings.playground_max_concurrency)

            async def _bounded() -> dict[str, Any]:
                async with sem:
                    status, headers, raw = await _call_router(
                        settings,
                        workload_bearer=workload_bearer,
                        body=request_body,
                        stream=False,
                    )
                    trace = {
                        k.lower(): v
                        for k, v in headers.items()
                        if k.lower().startswith("x-aap-")
                        or k.lower() in {"x-request-id", "x-router-trace"}
                    }
                    if status >= 400:
                        raise RouterUpstreamError(f"router returned {status}")
                    body_out = json.loads(raw.decode("utf-8"))
                    return {"trace": trace, "response": body_out}

            results = await asyncio.gather(
                *[_bounded() for _ in resolved_ids], return_exceptions=True
            )
            outputs: list[Any] = []
            for item in results:
                if isinstance(item, BaseException):
                    outputs.append({"error": str(item)})
                    final_status = "failed"
                else:
                    outputs.append(item)
                    router_trace = {**router_trace, **item.get("trace", {})}
            output = {"variants": outputs}
        else:
            status, headers, raw = await _call_router(
                settings,
                workload_bearer=workload_bearer,
                body=request_body,
                stream=payload.stream,
            )
            router_trace = {
                k.lower(): v
                for k, v in headers.items()
                if k.lower().startswith("x-aap-") or k.lower() in {"x-request-id", "x-router-trace"}
            }
            router_request_id = headers.get("x-request-id") or headers.get("X-Request-Id")
            if status >= 400:
                raise RouterUpstreamError(f"router returned {status}")
            if payload.stream:
                output = {
                    "stream_bytes": len(raw),
                    "raw_prefix": raw[:512].decode("utf-8", errors="replace"),
                }
            else:
                output = json.loads(raw.decode("utf-8"))
    except (RouterUpstreamError, json.JSONDecodeError, httpx.HTTPError) as exc:
        final_status = "failed"
        error_message = str(exc)[:2000]

    output_digest = sha256_hex(json.dumps(output or {}, sort_keys=True).encode("utf-8"))
    repo.finalize_playground_run(
        conn,
        org_id=org_id,
        run_id=run_id,
        status=final_status,
        router_request_id=router_request_id,
        router_trace=router_trace,
        input_digest=input_digest,
        output_digest=output_digest,
        error_message=error_message,
    )
    repo.insert_audit(
        conn,
        org_id=org_id,
        project_id=project_id,
        action="playground.run",
        resource_type="playground_run",
        resource_id=run_id,
        actor=principal.actor,
        detail={"mode": payload.mode, "resolved_revision_ids": [str(i) for i in resolved_ids]},
    )
    return PlaygroundRunResponse(
        run_id=run_id,
        mode=payload.mode,
        status=final_status,
        resolved_revision_ids=resolved_ids,
        model_alias=payload.model_alias,
        router_trace=router_trace,
        output=output,
        error_message=error_message,
    )


async def replay_playground(
    conn: PgConn,
    settings: Settings,
    *,
    principal: InternalPrincipal,
    run_id: UUID,
    workload_bearer: str | None,
) -> PlaygroundRunResponse:
    prior = repo.get_playground_run(conn, principal.organization_id, principal.project_id, run_id)
    if prior is None:
        raise NotFoundError("playground run not found")
    refs = [ArtifactRef(revision_id=UUID(str(r))) for r in prior["resolved_revision_ids"]]
    req = PlaygroundRunRequest(
        mode="replay",
        artifacts=refs,
        variables=dict(prior.get("variables") or {}),
        model_alias=str(prior["model_alias"]),
        replay_run_id=run_id,
    )
    return await run_playground(
        conn, settings, principal=principal, payload=req, workload_bearer=workload_bearer
    )
