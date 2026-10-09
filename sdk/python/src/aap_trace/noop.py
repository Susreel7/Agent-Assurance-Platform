"""No-op tracer provider when SDK is disabled."""

from __future__ import annotations

from opentelemetry.trace import NoOpTracerProvider as _OtelNoOpTracerProvider


class NoopTracerProvider(_OtelNoOpTracerProvider):
    """Extended no-op with shutdown hooks."""

    def shutdown(self) -> None:  # noqa: D401
        """No-op."""

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
