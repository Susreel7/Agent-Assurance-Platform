"""Domain errors for the edge collector."""

from __future__ import annotations


class CollectorError(Exception):
    code: str = "collector_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class InvalidEnvelopeError(CollectorError):
    code = "invalid_envelope"


class PayloadTooLargeError(CollectorError):
    code = "payload_too_large"


class SpoolQuotaError(CollectorError):
    code = "spool_quota_exceeded"
