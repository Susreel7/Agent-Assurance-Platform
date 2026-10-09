"""Bounded domain errors for Observe."""

from __future__ import annotations


class ObserveError(Exception):
    """Base error with a stable machine code."""

    code: str = "observe_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class AuthenticationError(ObserveError):
    code = "authentication_failed"


class AuthorizationError(ObserveError):
    code = "authorization_failed"


class PayloadTooLargeError(ObserveError):
    code = "payload_too_large"


class InvalidEnvelopeError(ObserveError):
    code = "invalid_envelope"


class IdempotencyConflictError(ObserveError):
    code = "idempotency_conflict"


class DependencyNotReadyError(ObserveError):
    code = "dependency_not_ready"


class UnsupportedProviderError(ObserveError):
    code = "unsupported_provider"
