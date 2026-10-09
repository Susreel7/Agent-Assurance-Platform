"""Shared health/readiness handlers."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from observe.config import Settings, get_settings


class ReadinessState(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


class DependencyStatus(BaseModel):
    name: str
    state: ReadinessState
    detail: str | None = None


class ReadinessResponse(BaseModel):
    state: ReadinessState
    dependencies: list[DependencyStatus] = Field(default_factory=list)


class VersionResponse(BaseModel):
    service: str
    build_revision: str
    contract_revision: str


def build_health_router(
    *,
    check_postgres: bool = False,
    check_clickhouse: bool = False,
    check_redis: bool = False,
    postgres_ping: Callable[[], None] | None = None,
    clickhouse_ping: Callable[[], None] | None = None,
    redis_ping: Callable[[], None] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "alive"}

    @router.get("/version", response_model=VersionResponse)
    def version(settings: Settings | None = None) -> VersionResponse:
        s = settings or get_settings()
        return VersionResponse(
            service=s.service_name,
            build_revision=s.build_revision,
            contract_revision=s.contract_revision,
        )

    @router.get("/readyz", response_model=ReadinessResponse)
    def readyz() -> ReadinessResponse:
        deps: list[DependencyStatus] = []
        overall = ReadinessState.OK

        if check_postgres and postgres_ping is not None:
            try:
                postgres_ping()
                deps.append(DependencyStatus(name="postgres", state=ReadinessState.OK))
            except Exception as exc:  # noqa: BLE001 — readiness boundary
                deps.append(
                    DependencyStatus(
                        name="postgres",
                        state=ReadinessState.NOT_READY,
                        detail=str(exc)[:256],
                    )
                )
                overall = ReadinessState.NOT_READY

        if check_clickhouse and clickhouse_ping is not None:
            try:
                clickhouse_ping()
                deps.append(DependencyStatus(name="clickhouse", state=ReadinessState.OK))
            except Exception as exc:  # noqa: BLE001
                deps.append(
                    DependencyStatus(
                        name="clickhouse",
                        state=ReadinessState.NOT_READY,
                        detail=str(exc)[:256],
                    )
                )
                overall = ReadinessState.NOT_READY

        if check_redis and redis_ping is not None:
            try:
                redis_ping()
                deps.append(DependencyStatus(name="redis", state=ReadinessState.OK))
            except Exception as exc:  # noqa: BLE001
                deps.append(
                    DependencyStatus(
                        name="redis",
                        state=ReadinessState.DEGRADED,
                        detail=str(exc)[:256],
                    )
                )
                if overall == ReadinessState.OK:
                    overall = ReadinessState.DEGRADED

        return ReadinessResponse(state=overall, dependencies=deps)

    return router


def freshness_payload(
    *,
    last_manifest_at: str | None,
    pending_manifests: int,
    clickhouse_lag_seconds: float | None,
) -> dict[str, Any]:
    if pending_manifests > 100:
        status = "degraded"
    elif pending_manifests > 0:
        status = "catching_up"
    else:
        status = "fresh"
    return {
        "status": status,
        "last_manifest_at": last_manifest_at,
        "last_ingest_at": last_manifest_at,
        "pending_manifests": pending_manifests,
        "pending_normalization": pending_manifests,
        "clickhouse_lag_seconds": clickhouse_lag_seconds,
    }
