"""Domain errors translated to HTTP in routers."""

from __future__ import annotations


class EvaluateError(Exception):
    code: str = "evaluate_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthenticationError(EvaluateError):
    code = "authentication_error"


class AuthorizationError(EvaluateError):
    code = "authorization_error"


class NotFoundError(EvaluateError):
    code = "not_found"


class ConflictError(EvaluateError):
    code = "conflict"


class ValidationError(EvaluateError):
    code = "validation_error"


class PreconditionFailedError(EvaluateError):
    code = "precondition_failed"


class PayloadTooLargeError(EvaluateError):
    code = "payload_too_large"


class EncryptionError(EvaluateError):
    code = "encryption_error"


class UpstreamError(EvaluateError):
    code = "upstream_error"


class JobCancelledError(EvaluateError):
    code = "job_cancelled"
