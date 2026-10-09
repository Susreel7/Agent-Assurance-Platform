"""Strict configuration — the only module that reads environment variables."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROTECTED_LABELS = frozenset({"production", "staging", "latest"})
ARTIFACT_KINDS = frozenset({"prompt", "rule", "skill", "context"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROMPT_", env_file=None, extra="ignore")

    service_name: str = "prompt"
    build_revision: str = "dev"
    contract_revision: str = "prompt-artifact-v1"

    database_url: str = Field(
        default="postgresql://prompt:prompt@localhost:5432/prompt",
        description="PostgreSQL URL; prompt schema migrations run on startup when enabled",
    )
    run_migrations_on_startup: bool = True

    internal_service_token: str = Field(
        default="dev-internal-token",
        description="Bearer token for console/control-plane human APIs",
    )

    introspection_url: str = Field(
        default="http://localhost:8000/v1/workload-credentials/-/introspect",
        description="Control-plane flat workload introspection endpoint",
    )
    introspection_timeout_seconds: float = 5.0
    required_runtime_scope: str = "prompt:read"
    required_runtime_module: str = "prompt"

    router_base_url: str = Field(
        default="http://localhost:8080",
        description="Go Router OpenAI-compatible base URL (no trailing slash)",
    )
    router_chat_path: str = "/v1/chat/completions"
    router_timeout_seconds: float = 120.0
    playground_max_variants: int = Field(default=4, ge=1, le=8)
    playground_max_concurrency: int = Field(default=2, ge=1, le=8)

    default_encryption_key_ref: str = "local:default"
    encryption_keys_json: str = Field(
        default="",
        description='JSON map key_ref -> Fernet urlsafe base64 key, e.g. {"local:default":"<key>"}',
    )

    max_body_bytes: int = Field(default=512 * 1024, ge=1024, le=4 * 1024 * 1024)
    runtime_cache_max_age_seconds: int = Field(default=60, ge=0, le=3600)
    runtime_cache_stale_if_error_seconds: int = Field(default=300, ge=0, le=86400)

    list_default_limit: int = Field(default=50, ge=1, le=200)
    list_max_limit: int = Field(default=200, ge=1, le=500)
    max_dependency_depth: int = Field(default=8, ge=1, le=32)

    router_integration_url: str | None = Field(
        default=None,
        description="When set, optional live router contract integration tests call this base URL",
    )

    redis_url: str | None = Field(
        default=None,
        description="Optional Redis for ephemeral playground cancel signals across instances",
    )
    redis_cancel_signal_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    redis_cancel_channel: str = "prompt:playground:cancel"
    playground_cancel_db_poll_seconds: float = Field(default=0.5, ge=0.1, le=5.0)
    playground_cancel_redis_poll_seconds: float = Field(default=0.25, ge=0.05, le=2.0)

    @field_validator("encryption_keys_json", mode="before")
    @classmethod
    def _strip_keys_json(cls, v: str | None) -> str:
        return (v or "").strip()

    def encryption_key_map(self) -> dict[str, str]:
        if not self.encryption_keys_json:
            return {}
        parsed = json.loads(self.encryption_keys_json)
        if not isinstance(parsed, dict):
            msg = "PROMPT_ENCRYPTION_KEYS_JSON must be a JSON object"
            raise ValueError(msg)
        out: dict[str, str] = {}
        for k, val in parsed.items():
            out[str(k)] = str(val)
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


SettingsDep = Literal["settings"]
