"""Observe query client for trace metadata and live-tail polling."""

from __future__ import annotations

import json
from typing import Any

import httpx
from httpx import AsyncBaseTransport

from evaluate.config import Settings
from evaluate.errors import UpstreamError


def _map_trace_detail(data: dict[str, Any]) -> dict[str, Any]:
    spans_raw = data.get("spans")
    spans: list[dict[str, Any]] = spans_raw if isinstance(spans_raw, list) else []
    root: dict[str, Any] = {}
    for span in spans:
        if isinstance(span, dict) and not span.get("parent_span_id"):
            root = span
            break
    if not root and spans and isinstance(spans[0], dict):
        root = spans[0]
    total_latency = sum(float(s.get("duration_ms") or 0) for s in spans if isinstance(s, dict))
    return {
        "trace_id": data.get("trace_id"),
        "root_span_id": root.get("span_id"),
        "span_id": root.get("span_id"),
        "latency_ms": int(total_latency) if total_latency else None,
        "outcome": root.get("outcome"),
        "model": root.get("model"),
        "truncated": bool(data.get("truncated")),
    }


class ObserveClient:
    def __init__(self, settings: Settings, *, transport: AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    def _base(self) -> str:
        return self._settings.observe_base_url.rstrip("/")

    async def get_trace_summary(
        self,
        *,
        org_id: str,
        project_id: str,
        trace_id: str,
        authorization: str,
    ) -> dict[str, Any]:
        url = f"{self._base()}/v1/traces/{trace_id}"
        params: dict[str, str | int] = {
            "organization_id": str(org_id),
            "project_id": str(project_id),
            "limit": 500,
        }
        async with httpx.AsyncClient(
            timeout=self._settings.upstream_timeout_seconds,
            transport=self._transport,
        ) as client:
            resp = await client.get(
                url,
                params=params,
                headers={"Authorization": authorization},
            )
        if resp.status_code == 404:
            return {}
        if resp.status_code >= 400:
            raise UpstreamError(f"observe trace fetch failed: {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            return {}
        return _map_trace_detail(data)

    async def poll_events(
        self,
        *,
        org_id: str,
        project_id: str,
        cursor: str,
        authorization: str,
    ) -> dict[str, Any]:
        """Read a bounded batch from Observe live-tail SSE (stream_events cursor)."""
        url = f"{self._base()}/v1/live-tail"
        params: dict[str, str] = {
            "organization_id": str(org_id),
            "project_id": str(project_id),
        }
        if cursor:
            params["cursor"] = cursor
        events: list[dict[str, Any]] = []
        next_cursor = cursor or "0"
        read_timeout = min(
            self._settings.observe_poll_live_tail_seconds,
            self._settings.upstream_timeout_seconds,
        )
        timeout = httpx.Timeout(5.0, read=read_timeout)
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            async with client.stream(
                "GET",
                url,
                params=params,
                headers={"Authorization": authorization},
            ) as resp:
                if resp.status_code >= 400:
                    raise UpstreamError(f"observe live-tail failed: {resp.status_code}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        payload = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("cursor") is not None:
                        next_cursor = str(payload["cursor"])
                    trace_id = payload.get("trace_id")
                    if trace_id:
                        meta: dict[str, object] = {
                            "event_type": payload.get("type"),
                            "span_id": payload.get("span_id"),
                        }
                        events.append({"trace_id": str(trace_id), "metadata": meta})
                    if len(events) >= self._settings.observe_poll_max_events:
                        break
        return {"events": events, "next_cursor": next_cursor}
