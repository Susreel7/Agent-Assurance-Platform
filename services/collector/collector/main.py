"""Edge OTLP collector HTTP service."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response

from collector.config import get_settings
from collector.errors import (
    CollectorError,
    InvalidEnvelopeError,
    PayloadTooLargeError,
    SpoolQuotaError,
)
from collector.forwarder import Forwarder
from collector.ingest import handle_ingest, handle_logs_ingest
from collector.metrics import CollectorMetrics
from collector.responses import error_response, prefers_protobuf
from collector.sampling import SamplingPolicyCache
from collector.spool import SpoolStore

log = logging.getLogger("collector")

IngestHandler = Callable[..., tuple[bytes, str, int]]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    spool: SpoolStore = app.state.spool
    forwarder: Forwarder = app.state.forwarder
    recovered = spool.recover_after_crash()
    if recovered:
        log.warning("recovered %d inflight spool entries after crash", recovered)
    forwarder.start()
    try:
        yield
    finally:
        await forwarder.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    spool = SpoolStore(Path(settings.spool_dir), disk_quota_bytes=settings.disk_quota_bytes)
    metrics = CollectorMetrics()
    sampling = SamplingPolicyCache(settings)
    forwarder = Forwarder(settings, spool, metrics)

    app = FastAPI(title="AAP Edge Collector", lifespan=lifespan)
    app.state.spool = spool
    app.state.forwarder = forwarder
    app.state.metrics = metrics
    app.state.settings = settings

    async def _ingest_response(
        request: Request,
        *,
        signal: str,
        handler: IngestHandler,
    ) -> Response:
        content_type = request.headers.get("Content-Type", "application/x-protobuf")
        accept = request.headers.get("Accept")
        as_proto = prefers_protobuf(content_type, accept)
        body = await request.body()
        try:
            payload, media, status = handler(
                settings,
                spool,
                metrics,
                body=body,
                content_type=content_type,
                content_encoding=request.headers.get("Content-Encoding"),
                accept=accept,
                traceparent=request.headers.get("traceparent"),
                tracestate=request.headers.get("tracestate"),
                sampling=sampling,
            )
            return Response(content=payload, status_code=status, media_type=media)
        except PayloadTooLargeError as exc:
            metrics.inc("ingest_rejected_envelope")
            body_out, media, code = error_response(
                status_code=413,
                code=exc.code,
                message=str(exc),
                as_protobuf=as_proto,
                signal=signal,
            )
            return Response(content=body_out, status_code=code, media_type=media)
        except SpoolQuotaError as exc:
            body_out, media, code = error_response(
                status_code=507,
                code=exc.code,
                message=str(exc),
                as_protobuf=as_proto,
                signal=signal,
            )
            return Response(content=body_out, status_code=code, media_type=media)
        except InvalidEnvelopeError as exc:
            metrics.inc("ingest_rejected_envelope")
            body_out, media, code = error_response(
                status_code=400,
                code=exc.code,
                message=str(exc),
                as_protobuf=as_proto,
                signal=signal,
            )
            return Response(content=body_out, status_code=code, media_type=media)
        except CollectorError as exc:
            metrics.inc("ingest_rejected_envelope")
            body_out, media, code = error_response(
                status_code=500,
                code=exc.code,
                message=str(exc),
                as_protobuf=as_proto,
                signal=signal,
            )
            return Response(content=body_out, status_code=code, media_type=media)

    @app.post("/v1/traces")
    async def post_traces(request: Request) -> Response:
        return await _ingest_response(request, signal="traces", handler=handle_ingest)

    @app.post("/v1/logs")
    async def post_logs(request: Request) -> Response:
        return await _ingest_response(request, signal="logs", handler=handle_logs_ingest)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, object]:
        pending = spool.pending_count()
        return {
            "status": "ready",
            "spool_pending": pending,
            "forwarder_running": forwarder.running,
        }

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        return Response(content=metrics.prometheus_text(), media_type="text/plain; version=0.0.4")

    return app


app = create_app()
