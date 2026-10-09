"""Shared health/readiness handlers."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from fastapi import APIRouter
from pydantic import BaseModel, Field

from prompt.config import get_settings


class ReadinessState(StrEnum):
    OK = "ok"
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
    postgres_ping: Callable[[], None] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "alive"}

    @router.get("/version", response_model=VersionResponse)
    def version() -> VersionResponse:
        s = get_settings()
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
        return ReadinessResponse(state=overall, dependencies=deps)

    return router
