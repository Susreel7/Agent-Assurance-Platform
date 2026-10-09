"""Strict configuration — the only module that reads environment variables."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObjectStoreKind(StrEnum):
    LOCAL = "local"
    S3 = "s3"
    AZURE = "azure"
    GCS = "gcs"


class CaptureMode(StrEnum):
    NONE = "none"
    DIGEST = "digest"
    REDACTED = "redacted"
    FULL = "full"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBSERVE_", env_file=None, extra="ignore")

    service_name: str = "observe"
    build_revision: str = "dev"
    contract_revision: str = "otel-ingest-v1"

    # Postgres (observe schema owner)
    database_url: str = Field(
        default="postgresql://observe:observe@localhost:5432/observe",
        description="PostgreSQL URL; observe schema migrations run on startup when enabled",
    )
    run_migrations_on_startup: bool = True

    # ClickHouse HTTP
    clickhouse_url: str = "http://localhost:8123"
    clickhouse_database: str = "observe"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_spans_ttl_days: int = Field(default=90, ge=1, le=3650)

    # Redis (wake-up only)
    redis_url: str | None = None
    redis_wake_channel: str = "observe:ingest:wake"

    # Object store
    object_store: ObjectStoreKind = ObjectStoreKind.LOCAL
    object_store_root: str = "/var/lib/aap/observe/objects"
    object_store_bucket: str = ""
    object_store_prefix: str = ""
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_kms_key_id: str = ""
    azure_storage_account_url: str = ""
    run_clickhouse_init_on_startup: bool = True
    redacted_preview_max_bytes: int = Field(default=512, ge=64, le=4096)
    payload_encryption_key: str = Field(
        default="",
        description="Fernet key for full-mode payload blobs; required when capture=full",
    )

    # Ingest limits (otel-ingest contract)
    max_compressed_bytes: int = 16 * 1024 * 1024
    max_uncompressed_bytes: int = 64 * 1024 * 1024
    max_spans_per_request: int = 10_000
    max_logs_per_request: int = 10_000

    # Control-plane workload introspection
    introspection_url: str = Field(
        default="http://localhost:8000/v1/workload-credentials/-/introspect",
        description="HTTP endpoint; Bearer token forwarded from ingest requests",
    )
    introspection_timeout_seconds: float = 5.0
    required_ingest_scope: str = "observe:ingest"

    # Query internal auth
    internal_service_token: str = Field(
        default="dev-internal-token",
        description="Shared secret for console/control-plane to query traces",
    )

    # Worker polling
    worker_poll_interval_seconds: float = 2.0
    worker_batch_size: int = 20
    worker_max_attempts: int = 8
    manifest_reconcile_interval_seconds: float = 30.0
    operations_projection_url: str = ""
    operations_projection_bearer: str = ""
    operations_projection_batch_size: int = Field(default=20, ge=1, le=500)
    operations_projection_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    retention_sweep_interval_seconds: float = Field(default=300.0, ge=10, le=86_400)
    retention_sweep_batch_size: int = Field(default=100, ge=1, le=10_000)
    air_gap_mode: bool = False

    # Query live tail
    live_tail_poll_seconds: float = 1.0
    live_tail_max_events: int = 100

    # Signed payload reference TTL
    payload_ref_sign_ttl_seconds: int = 300
    max_payload_content_bytes: int = 1_048_576

    @field_validator("object_store", mode="before")
    @classmethod
    def _normalize_store(cls, v: str | ObjectStoreKind) -> ObjectStoreKind:
        if isinstance(v, ObjectStoreKind):
            return v
        return ObjectStoreKind(str(v).lower())

    @model_validator(mode="after")
    def _air_gap_has_no_external_projection(self) -> Settings:
        if not self.air_gap_mode or not self.operations_projection_url:
            return self
        from urllib.parse import urlsplit

        host = (urlsplit(self.operations_projection_url).hostname or "").lower()
        if host not in {"api", "localhost", "127.0.0.1", "::1"}:
            raise ValueError(
                "OBSERVE_OPERATIONS_PROJECTION_URL must be local when OBSERVE_AIR_GAP_MODE=true"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


SettingsMode = Literal["ingest", "worker", "query"]
