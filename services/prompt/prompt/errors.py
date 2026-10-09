"""Domain errors translated to HTTP in routers."""

from __future__ import annotations


class PromptError(Exception):
    code: str = "prompt_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthenticationError(PromptError):
    code = "authentication_error"


class AuthorizationError(PromptError):
    code = "authorization_error"


class NotFoundError(PromptError):
    code = "not_found"


class ConflictError(PromptError):
    code = "conflict"


class ValidationError(PromptError):
    code = "validation_error"


class PreconditionFailedError(PromptError):
    code = "precondition_failed"


class PayloadTooLargeError(PromptError):
    code = "payload_too_large"


class EncryptionError(PromptError):
    code = "encryption_error"


class RouterUpstreamError(PromptError):
    code = "router_upstream_error"
