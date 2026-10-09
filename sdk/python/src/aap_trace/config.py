"""SDK configuration — no os.environ reads; callers pass explicit values or use from_env helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from aap_trace.capture import CaptureMode


def _env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


@dataclass(slots=True)
class TraceConfig:
    """Connection and identity for Observe OTLP ingest."""

    endpoint: str
    bearer_token: str
    organization_id: str
    project_id: str
    agent_id: str | None = None
    agent_name: str | None = None
    agent_version: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    actor_id: str | None = None
    actor_type: str | None = None
    invocation_source: str | None = None
    application_name: str | None = None
    client_name: str | None = None
    request_id: str | None = None
    replay_of_execution_id: str | None = None
    environment: str = "production"
    service_name: str = "agent-runtime"
    enabled: bool = True
    capture_mode: CaptureMode = CaptureMode.NONE
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    score_base_url: str | None = None
    otlp_timeout_seconds: float = 10.0
    max_export_batch_size: int = 512
    schedule_delay_millis: int = 5000
    sample_rate: float = 1.0

    def __post_init__(self) -> None:
        if not 0 <= self.sample_rate <= 1:
            raise ValueError("sample_rate must be between 0 and 1")

    @classmethod
    def from_otel_env(
        cls,
        *,
        bearer_token: str | None = None,
        organization_id: str | None = None,
        project_id: str | None = None,
        **overrides: object,
    ) -> TraceConfig:
        """Build config from standard OTEL_* variables plus AAP identity overrides."""
        endpoint = str(
            overrides.pop("endpoint", None)
            or _env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
            or _env("OTEL_EXPORTER_OTLP_ENDPOINT")
            or ""
        )
        token = bearer_token or _env("AAP_WORKLOAD_TOKEN") or _env("AAP_BEARER_TOKEN") or ""
        org = organization_id or _env("AAP_ORGANIZATION_ID") or ""
        project = project_id or _env("AAP_PROJECT_ID") or ""
        enabled_raw = _env("OTEL_SDK_DISABLED", "false") or "false"
        enabled = enabled_raw.lower() not in {"true", "1", "yes"}
        capture_raw = _env("AAP_CAPTURE_MODE", "none") or "none"
        capture = CaptureMode(capture_raw.lower())
        base: dict[str, object] = {
            "endpoint": endpoint,
            "bearer_token": token,
            "organization_id": org,
            "project_id": project,
            "agent_id": _env("AAP_AGENT_ID"),
            "agent_name": _env("AAP_AGENT_NAME"),
            "agent_version": _env("AAP_AGENT_VERSION"),
            "session_id": _env("AAP_SESSION_ID") or _env("GEN_AI_CONVERSATION_ID"),
            "user_id": _env("AAP_USER_ID"),
            "actor_id": _env("AAP_ACTOR_ID"),
            "actor_type": _env("AAP_ACTOR_TYPE"),
            "invocation_source": _env("AAP_INVOCATION_SOURCE"),
            "application_name": _env("AAP_APPLICATION_NAME"),
            "client_name": _env("AAP_CLIENT_NAME"),
            "request_id": _env("AAP_REQUEST_ID"),
            "replay_of_execution_id": _env("AAP_REPLAY_OF_EXECUTION_ID"),
            "environment": _env("DEPLOYMENT_ENVIRONMENT")
            or _env("AAP_ENVIRONMENT")
            or "production",
            "service_name": _env("OTEL_SERVICE_NAME") or "agent-runtime",
            "enabled": enabled,
            "capture_mode": capture,
            "score_base_url": _env("AAP_SCORE_BASE_URL"),
            "sample_rate": float(_env("AAP_SAMPLE_RATE", "1") or "1"),
        }
        base.update(overrides)
        return cls(**base)  # type: ignore[arg-type]
