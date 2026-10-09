"""Strict configuration — the only module that reads environment variables."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CaptureMode(StrEnum):
    NONE = "none"
    DIGEST = "digest"
    REDACTED = "redacted"
    FULL = "full"


class RedactionRule(BaseModel):
    pattern: str
    replacement: str = "[redacted]"

    @field_validator("pattern")
    @classmethod
    def _compile_check(cls, value: str) -> str:
        re.compile(value)
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COLLECTOR_", env_file=None, extra="ignore")

    service_name: str = "aap-collector"
    build_revision: str = "dev"

    observe_ingest_url: str = Field(
        default="http://localhost:8080/v1/traces",
        description="Observe OTLP ingest POST /v1/traces",
    )
    observe_logs_ingest_url: str = Field(
        default="",
        description="Observe OTLP ingest POST /v1/logs; derived from trace URL when unset",
    )
    workload_bearer_token: str = Field(
        default="",
        description="Bearer token for outbound forward only; never log or persist",
    )
    sampling_policy_url: str = ""
    sampling_policy_bearer_token: str = Field(default="", repr=False)
    sampling_policy_cache_seconds: float = Field(default=30, ge=1, le=3600)
    sampling_policy_timeout_seconds: float = Field(default=2, ge=0.1, le=10)
    sample_rate: float = Field(default=1.0, ge=0, le=1)

    spool_dir: str = "/var/lib/aap/collector/spool"
    disk_quota_bytes: int = Field(default=512 * 1024 * 1024, ge=512)

    capture_mode: CaptureMode = CaptureMode.DIGEST
    redacted_preview_max_bytes: int = Field(default=512, ge=64, le=4096)
    redaction_regex_rules: list[RedactionRule] = Field(default_factory=list)

    max_compressed_bytes: int = 16 * 1024 * 1024
    max_uncompressed_bytes: int = 64 * 1024 * 1024
    max_spans_per_request: int = 10_000
    max_logs_per_request: int = 10_000

    poison_attempt_threshold: int = Field(default=8, ge=1, le=100)
    forward_base_delay_seconds: float = Field(default=0.5, ge=0.0)
    forward_max_delay_seconds: float = Field(default=120.0, ge=1.0)
    forward_jitter_ratio: float = Field(default=0.2, ge=0.0, le=1.0)
    forward_poll_seconds: float = Field(default=1.0, ge=0.01)
    forward_http_timeout_seconds: float = Field(default=30.0, ge=1.0)

    log_level: str = "INFO"

    @field_validator("redaction_regex_rules", mode="before")
    @classmethod
    def _parse_redaction_rules(cls, value: object) -> list[RedactionRule]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [RedactionRule.model_validate(item) for item in value]
        if isinstance(value, str):
            data = json.loads(value)
            if not isinstance(data, list):
                raise ValueError("redaction_regex_rules must be a JSON array")
            return [RedactionRule.model_validate(item) for item in data]
        raise ValueError("invalid redaction_regex_rules")

    @model_validator(mode="after")
    def _derive_logs_ingest_url(self) -> Self:
        if self.observe_logs_ingest_url:
            return self
        traces = self.observe_ingest_url
        if traces.endswith("/v1/traces"):
            self.observe_logs_ingest_url = traces[: -len("/v1/traces")] + "/v1/logs"
        else:
            self.observe_logs_ingest_url = "http://localhost:8080/v1/logs"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
