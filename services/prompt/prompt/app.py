"""Prompt artifact workspace HTTP application."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from prompt.config import get_settings
from prompt.db.postgres import ping as pg_ping
from prompt.domains.artifacts.router import router as artifacts_router
from prompt.domains.audit.router import router as audit_router
from prompt.domains.labels.router import router as labels_router
from prompt.domains.playground.router import router as playground_router
from prompt.domains.runtime.internal_router import router as runtime_internal_router
from prompt.domains.runtime.router import router as runtime_router
from prompt.errors import AuthenticationError, PromptError, ValidationError
from prompt.health import build_health_router
from prompt.migrations.runner import apply_migrations

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.run_migrations_on_startup:
        try:
            apply_migrations(settings.database_url)
        except Exception:  # noqa: BLE001
            log.exception("prompt migrations failed on startup")

    app = FastAPI(title="Prompt", version="0.1.0")
    app.include_router(
        build_health_router(
            check_postgres=True,
            postgres_ping=lambda: pg_ping(settings.database_url),
        )
    )
    app.include_router(artifacts_router)
    app.include_router(labels_router)
    app.include_router(runtime_router)
    app.include_router(runtime_internal_router)
    app.include_router(playground_router)
    app.include_router(audit_router)

    @app.exception_handler(AuthenticationError)
    async def _auth(_request: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(ValidationError)
    async def _validation(_request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(PromptError)
    async def _prompt(_request: Request, exc: PromptError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"code": exc.code, "message": exc.message})

    return app
