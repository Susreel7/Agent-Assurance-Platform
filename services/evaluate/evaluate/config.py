"""Strict configuration — the only module that reads environment variables."""

from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EVALUATOR_KINDS = frozenset(
    {
        "exact_match",
        "regex",
        "json_schema",
        "latency_ms",
        "cost_usd",
        "tool_trajectory",
        "python_function",
        "llm_judge",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EVALUATE_", env_file=None, extra="ignore")

    service_name: str = "evaluate"
    build_revision: str = "dev"
    contract_revision: str = "evaluate-workspace-v1"

    database_url: str = Field(
        default="postgresql://evaluate:evaluate@localhost:5432/evaluate",
    )
    run_migrations_on_startup: bool = True

    internal_service_token: str = Field(default="dev-internal-token")
    introspection_url: str = Field(
        default="http://localhost:8000/v1/workload-credentials/-/introspect",
    )
    introspection_timeout_seconds: float = 5.0
    required_workload_module: str = "evaluate"
    required_workload_scope: str = "evaluate:write"

    prompt_base_url: str = Field(default="http://localhost:8095")
    prompt_workload_bearer: str = Field(
        default="",
        description="Workload bearer for Prompt runtime fetch; falls back to internal token when empty",
    )
    router_base_url: str = Field(default="http://localhost:8080")
    router_worker_bearer: str = Field(
        default="",
        description="Bearer for Router calls from worker; required in production worker mode",
    )
    observe_base_url: str = Field(default="http://localhost:8092")
    observe_worker_bearer: str = Field(default="")
    upstream_timeout_seconds: float = 120.0
    observe_poll_interval_seconds: float = Field(default=15.0, ge=1.0, le=300.0)
    observe_poll_max_events: int = Field(default=20, ge=1, le=100)
    observe_poll_live_tail_seconds: float = Field(default=12.0, ge=2.0, le=60.0)

    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_wake_channel: str = "evaluate:jobs:wake"
    redis_enabled: bool = True

    worker_poll_interval_seconds: float = 2.0
    worker_job_lease_seconds: int = 120
    worker_max_attempts: int = 5
    reconciler_interval_seconds: float = 30.0

    default_encryption_key_ref: str = "local:default"
    encryption_keys_json: str = Field(default="")

    inline_metadata_max_bytes: int = Field(default=4096, ge=256, le=65536)
    inline_content_max_bytes: int = Field(default=32 * 1024, ge=1024, le=256 * 1024)
    max_body_bytes: int = Field(default=512 * 1024, ge=1024, le=4 * 1024 * 1024)

    list_default_limit: int = Field(default=50, ge=1, le=200)
    list_max_limit: int = Field(default=200, ge=1, le=500)

    python_eval_timeout_seconds: float = Field(default=30.0, ge=0.5, le=120.0)
    python_eval_memory_mb: int = Field(default=128, ge=32, le=512)
    python_sandbox_mode: str = Field(default="development", pattern="^(development|production)$")

    object_store_backend: str = Field(default="local", pattern="^(local|s3|azure|gcs)$")
    object_store_local_root: str = Field(default="./data/evaluate-objects")
    object_store_s3_bucket: str = ""
    object_store_s3_region: str = ""
    object_store_s3_prefix: str = "evaluate"
    object_store_azure_container: str = ""
    object_store_azure_account_url: str = ""
    object_store_gcs_bucket: str = ""
    object_store_gcs_prefix: str = "evaluate"
    download_signing_secret: str = Field(default="dev-download-signing-secret")
    download_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    online_default_sample_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    experiment_default_concurrency: int = Field(default=2, ge=1, le=32)
    experiment_default_repetitions: int = Field(default=1, ge=1, le=100)

    api_port: int = 8096

    @field_validator("encryption_keys_json", mode="before")
    @classmethod
    def _strip_keys_json(cls, v: str | None) -> str:
        return (v or "").strip()

    def encryption_key_map(self) -> dict[str, str]:
        if not self.encryption_keys_json:
            return {}
        parsed = json.loads(self.encryption_keys_json)
        if not isinstance(parsed, dict):
            msg = "EVALUATE_ENCRYPTION_KEYS_JSON must be a JSON object"
            raise ValueError(msg)
        return {str(k): str(v) for k, v in parsed.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
