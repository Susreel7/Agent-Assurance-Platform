"""SSE passthrough from router to playground client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx

from prompt.config import Settings
from prompt.db import repository as repo
from prompt.db.postgres import connect
from prompt.domains.playground.cancel_coordinator import StreamCancelCoordinator
from prompt.domains.playground.cancel_registry import cancel as signal_local_cancel
from prompt.domains.playground.cancel_registry import drop
from prompt.errors import RouterUpstreamError
from prompt.validation.canonicalize import sha256_hex


async def stream_router_sse(
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    run_id: UUID,
    request_body: dict[str, Any],
    workload_bearer: str | None,
    disconnect: Any,
) -> AsyncIterator[bytes]:
    coordinator = StreamCancelCoordinator(
        settings, org_id=org_id, project_id=project_id, run_id=run_id
    )
    await coordinator.start()
    url = settings.router_base_url.rstrip("/") + settings.router_chat_path
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if workload_bearer:
        headers["Authorization"] = f"Bearer {workload_bearer}"

    collected: list[bytes] = []
    router_trace: dict[str, Any] = {}
    router_request_id: str | None = None
    final_status = "completed"
    error_message: str | None = None

    try:
        timeout = httpx.Timeout(settings.router_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json={**request_body, "stream": True},
            ) as resp:
                router_trace = {
                    k.lower(): v
                    for k, v in resp.headers.items()
                    if k.lower().startswith("x-aap-")
                    or k.lower() in {"x-request-id", "x-router-trace"}
                }
                router_request_id = resp.headers.get("x-request-id")
                if resp.status_code >= 400:
                    raise RouterUpstreamError(f"router returned {resp.status_code}")
                async for chunk in resp.aiter_bytes():
                    if coordinator.cancelled():
                        final_status = "cancelled"
                        error_message = "cancel requested"
                        await resp.aclose()
                        break
                    if await disconnect():
                        await signal_local_cancel(run_id)
                        final_status = "cancelled"
                        error_message = "client disconnected"
                        await resp.aclose()
                        break
                    collected.append(chunk)
                    yield chunk
    except (RouterUpstreamError, httpx.HTTPError) as exc:
        final_status = "failed"
        error_message = str(exc)[:2000]
        payload = json.dumps({"error": error_message})
        yield f"event: error\ndata: {payload}\n\n".encode()
    finally:
        await coordinator.stop()
        with connect(settings.database_url) as conn:
            row = repo.get_playground_run(conn, org_id, project_id, run_id)
            if row is not None and str(row.get("status")) == "cancel_requested":
                final_status = "cancelled"
                error_message = error_message or "cancel requested"
        output_digest = sha256_hex(b"".join(collected))
        with connect(settings.database_url) as conn:
            repo.finalize_playground_run(
                conn,
                org_id=org_id,
                run_id=run_id,
                status=final_status,
                router_request_id=router_request_id,
                router_trace=router_trace,
                input_digest=sha256_hex(json.dumps(request_body, sort_keys=True).encode("utf-8")),
                output_digest=output_digest,
                error_message=error_message,
            )
        await drop(run_id)
