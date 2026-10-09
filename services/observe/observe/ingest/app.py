"""OTLP ingest HTTP service."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response

from observe.auth import workload as workload_auth
from observe.config import get_settings
from observe.db.postgres import ping as pg_ping
from observe.errors import (
    AuthenticationError,
    AuthorizationError,
    IdempotencyConflictError,
    InvalidEnvelopeError,
    ObserveError,
    PayloadTooLargeError,
)
from observe.health import build_health_router
from observe.ingest import service as ingest_service
from observe.ingest.responses import error_response, prefers_protobuf
from observe.migrations.runner import apply_migrations
from observe.providers.object_store.factory import build_object_store

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.run_migrations_on_startup:
        try:
            apply_migrations(settings.database_url)
        except Exception:  # noqa: BLE001
            log.exception("observe migrations failed on startup")

    store = build_object_store(settings)
    app = FastAPI(title="Observe Ingest", version="0.1.0")
    app.include_router(
        build_health_router(
            check_postgres=True,
            check_redis=False,
            postgres_ping=lambda: pg_ping(settings.database_url),
        )
    )

    @app.post("/v1/traces")
    async def post_traces(request: Request) -> Response:
        content_type = request.headers.get("Content-Type", "application/x-protobuf")
        accept = request.headers.get("Accept")
        as_proto = prefers_protobuf(content_type, accept)
        try:
            principal = await workload_auth.introspect_bearer(
                settings, request.headers.get("Authorization")
            )
            body = await request.body()
            content_encoding = request.headers.get("Content-Encoding")
            payload, media, status = await ingest_service.ingest_traces(
                settings,
                store,
                principal=principal,
                body=body,
                content_type=content_type,
                content_encoding=content_encoding,
                accept=accept,
            )
            return Response(content=payload, status_code=status, media_type=media)
        except PayloadTooLargeError as exc:
            body, media, code = error_response(
                status_code=413, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except AuthenticationError as exc:
            body, media, code = error_response(
                status_code=401, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except AuthorizationError as exc:
            body, media, code = error_response(
                status_code=403, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except IdempotencyConflictError as exc:
            body, media, code = error_response(
                status_code=409, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except InvalidEnvelopeError as exc:
            body, media, code = error_response(
                status_code=400, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except ObserveError as exc:
            body, media, code = error_response(
                status_code=500, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)

    @app.post("/v1/logs")
    async def post_logs(request: Request) -> Response:
        content_type = request.headers.get("Content-Type", "application/x-protobuf")
        accept = request.headers.get("Accept")
        as_proto = prefers_protobuf(content_type, accept)
        try:
            principal = await workload_auth.introspect_bearer(
                settings, request.headers.get("Authorization")
            )
            body = await request.body()
            content_encoding = request.headers.get("Content-Encoding")
            payload, media, status = await ingest_service.ingest_logs(
                settings,
                store,
                principal=principal,
                body=body,
                content_type=content_type,
                content_encoding=content_encoding,
                accept=accept,
            )
            return Response(content=payload, status_code=status, media_type=media)
        except PayloadTooLargeError as exc:
            body, media, code = error_response(
                status_code=413, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except AuthenticationError as exc:
            body, media, code = error_response(
                status_code=401, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except AuthorizationError as exc:
            body, media, code = error_response(
                status_code=403, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except IdempotencyConflictError as exc:
            body, media, code = error_response(
                status_code=409, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except InvalidEnvelopeError as exc:
            body, media, code = error_response(
                status_code=400, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)
        except ObserveError as exc:
            body, media, code = error_response(
                status_code=500, code=exc.code, message=str(exc), as_protobuf=as_proto
            )
            return Response(content=body, status_code=code, media_type=media)

    return app
