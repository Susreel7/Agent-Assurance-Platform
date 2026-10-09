"""Fail-open project sampling policy cache for the edge collector."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from uuid import UUID

import httpx

from collector.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SamplingPolicy:
    head_sample_rate: float = 1.0
    tail_keep_errors: bool = True
    tail_keep_retries: bool = True
    tail_keep_high_latency: bool = True
    high_latency_ms: float = 10000
    max_traces_per_minute: int | None = None
    revision: int = 0


class SamplingPolicyCache:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[tuple[str, str], tuple[float, SamplingPolicy]] = {}
        self._rate_windows: dict[tuple[str, str], tuple[int, dict[bytes, bool]]] = {}
        self._lock = threading.Lock()

    def get(self, organization_id: str | None, project_id: str | None) -> SamplingPolicy:
        fallback = SamplingPolicy(head_sample_rate=self._settings.sample_rate)
        if (
            not organization_id
            or not project_id
            or not self._settings.sampling_policy_url
            or not self._settings.sampling_policy_bearer_token
        ):
            return fallback
        try:
            UUID(organization_id)
            UUID(project_id)
        except ValueError:
            return fallback
        key = (organization_id, project_id)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._settings.sampling_policy_cache_seconds:
                return cached[1]
        try:
            response = httpx.get(
                self._settings.sampling_policy_url,
                params={
                    "organization_id": organization_id,
                    "project_id": project_id,
                },
                headers={"Authorization": f"Bearer {self._settings.sampling_policy_bearer_token}"},
                timeout=self._settings.sampling_policy_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            policy = SamplingPolicy(
                head_sample_rate=float(body.get("head_sample_rate", 1)),
                tail_keep_errors=bool(body.get("tail_keep_errors", True)),
                tail_keep_retries=bool(body.get("tail_keep_retries", True)),
                tail_keep_high_latency=bool(body.get("tail_keep_high_latency", True)),
                high_latency_ms=float(body.get("high_latency_ms", 10000)),
                max_traces_per_minute=body.get("max_traces_per_minute"),
                revision=int(body.get("revision", 0)),
            )
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            log.warning("sampling policy unavailable; using fail-open local policy: %s", exc)
            return fallback
        with self._lock:
            self._cache[key] = (now, policy)
        return policy

    def allow_trace(
        self,
        organization_id: str | None,
        project_id: str | None,
        trace_id: bytes,
        maximum: int | None,
    ) -> bool:
        if maximum is None or not organization_id or not project_id:
            return True
        key = (organization_id, project_id)
        minute = int(time.time() // 60)
        with self._lock:
            window_minute, decisions = self._rate_windows.get(key, (minute, {}))
            if window_minute != minute:
                decisions = {}
                self._rate_windows[key] = (minute, decisions)
            if trace_id in decisions:
                return decisions[trace_id]
            allowed = sum(decisions.values()) < maximum
            decisions[trace_id] = allowed
            self._rate_windows[key] = (minute, decisions)
            return allowed
