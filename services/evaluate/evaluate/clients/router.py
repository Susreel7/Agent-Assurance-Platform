"""Go Router OpenAI-compatible client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from httpx import AsyncBaseTransport

from evaluate.config import Settings
from evaluate.errors import UpstreamError


@dataclass(frozen=True, slots=True)
class RouterChatResult:
    body: dict[str, Any]
    trace_id: str | None
    span_id: str | None
    traceparent: str | None
    request_id: str | None


def _header_trace_ids(
    headers: httpx.Headers,
) -> tuple[str | None, str | None, str | None, str | None]:
    trace_id = headers.get("x-trace-id") or headers.get("x-request-id")
    span_id = headers.get("x-span-id")
    traceparent = headers.get("traceparent")
    request_id = headers.get("x-request-id")
    return trace_id, span_id, traceparent, request_id


class RouterClient:
    def __init__(self, settings: Settings, *, transport: AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    async def chat_completions(
        self,
        *,
        body: dict[str, Any],
        authorization: str,
        idempotency_key: str | None = None,
    ) -> RouterChatResult:
        url = f"{self._settings.router_base_url.rstrip('/')}/v1/chat/completions"
        headers = {"Authorization": authorization, "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(
            timeout=self._settings.upstream_timeout_seconds,
            transport=self._transport,
        ) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code >= 400:
            raise UpstreamError(f"router chat failed: {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            raise UpstreamError("router returned non-object")
        tid, sid, tp, rid = _header_trace_ids(resp.headers)
        if not tid and isinstance(data.get("id"), str):
            tid = data["id"]
        return RouterChatResult(
            body=data,
            trace_id=tid,
            span_id=sid,
            traceparent=tp,
            request_id=rid,
        )
