"""Evaluate workspace HTTP application."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from evaluate.config import get_settings
from evaluate.db.postgres import ping as pg_ping
from evaluate.domains.annotation.router import router as annotation_router
from evaluate.domains.datasets.router import router as datasets_router
from evaluate.domains.evaluators.router import router as evaluators_router
from evaluate.domains.experiments.router import router as experiments_router
from evaluate.domains.online_rules.router import router as online_rules_router
from evaluate.domains.release_gate.router import router as release_gate_router
from evaluate.domains.scores.router import router as scores_router
from evaluate.errors import AuthenticationError, AuthorizationError, EvaluateError, ValidationError
from evaluate.health import build_health_router
from evaluate.migrations.runner import apply_migrations

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.run_migrations_on_startup:
        try:
            apply_migrations(settings.database_url)
        except Exception:  # noqa: BLE001
            log.exception("evaluate migrations failed on startup")

    app = FastAPI(title="Evaluate", version="0.1.0")
    app.include_router(
        build_health_router(
            check_postgres=True,
            postgres_ping=lambda: pg_ping(settings.database_url),
        )
    )
    app.include_router(datasets_router)
    app.include_router(experiments_router)
    app.include_router(evaluators_router)
    app.include_router(scores_router)
    app.include_router(online_rules_router)
    app.include_router(annotation_router)
    app.include_router(release_gate_router)

    @app.exception_handler(AuthenticationError)
    async def _auth(_request: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(AuthorizationError)
    async def _authz(_request: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(ValidationError)
    async def _validation(_request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(EvaluateError)
    async def _evaluate(_request: Request, exc: EvaluateError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"code": exc.code, "message": exc.message})

    return app
