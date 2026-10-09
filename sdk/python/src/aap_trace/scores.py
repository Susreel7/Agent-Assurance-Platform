"""Score / feedback client for the control-plane evaluate workload ingest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from aap_trace.config import TraceConfig


@dataclass(slots=True)
class ScoreRecord:
    name: str
    value: float
    trace_id: str | None = None
    span_id: str | None = None
    session_id: str | None = None
    comment: str | None = None
    metadata: Mapping[str, str] | None = None
    source: str = "human"


def _score_target(score: ScoreRecord) -> tuple[str, str]:
    if score.span_id:
        return "span", score.span_id
    if score.trace_id:
        return "trace", score.trace_id
    if score.session_id:
        return "session", score.session_id
    msg = "score requires trace_id, span_id, or session_id"
    raise ValueError(msg)


def _score_body(score: ScoreRecord) -> dict[str, Any]:
    target_type, target_id = _score_target(score)
    body: dict[str, Any] = {
        "target_type": target_type,
        "target_id": target_id,
        "name": score.name,
        "value_type": "numeric",
        "value_numeric": score.value,
        "source": score.source,
    }
    if score.comment:
        body["explanation"] = score.comment
    if score.metadata:
        body["metadata"] = dict(score.metadata)
    return body


class ScoreClient:
    """POST human or automated scores; never logs bearer token or comment bodies."""

    def __init__(self, config: TraceConfig) -> None:
        self._config = config
        base = config.score_base_url or config.endpoint.rsplit("/v1/", 1)[0]
        self._url = f"{base.rstrip('/')}/v1/evaluate/workload/scores"
        self._headers = {
            "Authorization": f"Bearer {config.bearer_token}",
            "Content-Type": "application/json",
        }

    def submit(self, score: ScoreRecord) -> None:
        if not self._config.enabled:
            return
        body = _score_body(score)
        with httpx.Client(timeout=self._config.otlp_timeout_seconds) as client:
            resp = client.post(self._url, headers=self._headers, json=body)
            resp.raise_for_status()

    async def submit_async(self, score: ScoreRecord) -> None:
        if not self._config.enabled:
            return
        body = _score_body(score)
        async with httpx.AsyncClient(timeout=self._config.otlp_timeout_seconds) as client:
            resp = await client.post(self._url, headers=self._headers, json=body)
            resp.raise_for_status()
