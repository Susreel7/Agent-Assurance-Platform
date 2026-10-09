"""Generic ASGI middleware for inbound W3C context."""

from __future__ import annotations

from aap_trace.context import extract_headers
from aap_trace.integrations._optional import require_package

require_package("starlette", "asgi")
from opentelemetry import context as otel_context  # noqa: E402
from starlette.types import ASGIApp, Receive, Scope, Send  # noqa: E402


class AAPTraceMiddleware:
    """Extract traceparent from HTTP requests and attach as current context."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        carrier = {
            "traceparent": headers.get("traceparent", ""),
            "tracestate": headers.get("tracestate", ""),
        }
        ctx = extract_headers({k: v for k, v in carrier.items() if v})
        token = otel_context.attach(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            otel_context.detach(token)
