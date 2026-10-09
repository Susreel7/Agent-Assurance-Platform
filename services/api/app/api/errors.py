"""The error envelope every failure leaves through.

The console currently renders "Something went wrong · Try again" for a 403 from a
permissions check, a 404 from a dead URL and a 500 from a genuine bug, because an HTTP
status and a free-text string are all it is given. Nothing in the UI can do better with
that, so the fix belongs here rather than in a React component.

Every error response carries five fields:

``reason``      a code from :class:`Reason`, which the console may branch on;
``message``     one sentence for a human, safe to show to whoever hit it;
``detail``      structured context — never free text the UI has to parse;
``next``        the action that resolves it, rendered as a button;
``request_id``  the id echoed in ``X-Request-Id``, quoted in every error surface.

The last one is what makes a support conversation possible: a screenshot of an error now
contains the key to the server-side log line that produced it.

Two rules keep this honest rather than decorative:

* ``ApiError`` is the only way a domain should refuse a request, and it *requires* a
  reason. There is no constructor that omits one.
* Legacy ``HTTPException`` still gets an envelope, translated by
  :func:`http_exception_handler`, because a route that has not been migrated must not be
  the one route whose failure the console cannot render. The translation is deliberately
  coarse; a route that wants a precise reason raises ``ApiError``.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"

_request_id: ContextVar[str] = ContextVar("aap_request_id", default="")


def current_request_id() -> str:
    return _request_id.get()


def bind_request_id(value: str) -> None:
    _request_id.set(value)


def new_request_id() -> str:
    return uuid.uuid4().hex


class Reason(StrEnum):
    """The closed vocabulary of refusals.

    The first block is the failure taxonomy in `design/02-identity-and-onboarding.md`;
    the console has a rendering for each. The second block covers the failures every
    HTTP API has, which the taxonomy does not name but which still may not reach a user
    as a bare status code.
    """

    # ---- identity and authorization (design/02) ----
    SESSION_EXPIRED = "session_expired"
    NOT_AUTHENTICATED = "not_authenticated"
    NOT_PROVISIONED = "not_provisioned"
    PROVIDER_DISABLED = "provider_disabled"
    PROVIDER_UNKNOWN = "provider_unknown"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    INVALID_CREDENTIAL = "invalid_credential"
    MEMBERSHIP_SUSPENDED = "membership_suspended"
    MFA_REQUIRED = "mfa_required"
    MODULE_FORBIDDEN = "module_forbidden"
    MODULE_NOT_ENTITLED = "module_not_entitled"
    SCOPE_OUTSIDE_GRANT = "scope_outside_grant"
    APPROVAL_PENDING = "approval_pending"
    POLICY_DENIED = "policy_denied"
    BUNDLE_STALE = "bundle_stale"

    # ---- the ordinary failures of any HTTP API ----
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_FAILED = "precondition_failed"
    RATE_LIMITED = "rate_limited"
    LICENCE_READ_ONLY = "licence_read_only"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    IDENTITY_PROVIDER_UNAVAILABLE = "identity_provider_unavailable"
    INTERNAL_ERROR = "internal_error"


class NextAction(StrEnum):
    """What the console renders as the button under the message."""

    SIGN_IN = "sign_in"
    RETRY = "retry"
    REQUEST_ACCESS = "request_access"
    CONTACT_OWNER = "contact_owner"
    REAUTHENTICATE = "reauthenticate"
    OPEN_REQUEST = "open_request"
    CONFIGURE_PROVIDER = "configure_provider"
    NONE = "none"


# reason -> (status, default sentence, default next action)
#
# The sentence is a default, not a constraint: a caller that knows the specific provider
# or role should pass a better one. What this table guarantees is that no reason can be
# raised without *some* human sentence attached.
_CATALOGUE: dict[Reason, tuple[int, str, NextAction]] = {
    Reason.SESSION_EXPIRED: (
        status.HTTP_401_UNAUTHORIZED,
        "Your session has expired.",
        NextAction.SIGN_IN,
    ),
    Reason.NOT_AUTHENTICATED: (
        status.HTTP_401_UNAUTHORIZED,
        "You are not signed in.",
        NextAction.SIGN_IN,
    ),
    Reason.NOT_PROVISIONED: (
        status.HTTP_401_UNAUTHORIZED,
        "Your account is not set up for this console yet.",
        NextAction.REQUEST_ACCESS,
    ),
    Reason.PROVIDER_DISABLED: (
        # 403, not 401. The caller did not fail to authenticate; the method they named is
        # one this deployment refuses to offer. A 401 would also carry
        # `WWW-Authenticate: Bearer`, telling a login screen to retry with a bearer
        # token, which is not a thing it has or could get.
        status.HTTP_403_FORBIDDEN,
        "That sign-in method is turned off for this account.",
        NextAction.CONTACT_OWNER,
    ),
    Reason.PROVIDER_UNKNOWN: (
        status.HTTP_404_NOT_FOUND,
        "That sign-in method does not exist for this account.",
        NextAction.SIGN_IN,
    ),
    Reason.PROVIDER_NOT_CONFIGURED: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "No sign-in method is configured for this deployment.",
        NextAction.CONFIGURE_PROVIDER,
    ),
    Reason.INVALID_CREDENTIAL: (
        status.HTTP_401_UNAUTHORIZED,
        "Those credentials were not accepted.",
        NextAction.SIGN_IN,
    ),
    Reason.MEMBERSHIP_SUSPENDED: (
        status.HTTP_403_FORBIDDEN,
        "Your membership of this account is suspended.",
        NextAction.CONTACT_OWNER,
    ),
    Reason.MFA_REQUIRED: (
        status.HTTP_401_UNAUTHORIZED,
        "Your organisation requires multi-factor authentication for this console.",
        NextAction.REAUTHENTICATE,
    ),
    Reason.MODULE_FORBIDDEN: (
        status.HTTP_403_FORBIDDEN,
        "You do not have permission to open this.",
        NextAction.REQUEST_ACCESS,
    ),
    Reason.MODULE_NOT_ENTITLED: (
        status.HTTP_403_FORBIDDEN,
        "This module is not included in the current licence.",
        NextAction.CONTACT_OWNER,
    ),
    Reason.SCOPE_OUTSIDE_GRANT: (
        status.HTTP_403_FORBIDDEN,
        "That is outside the part of the organisation you can see.",
        NextAction.REQUEST_ACCESS,
    ),
    Reason.APPROVAL_PENDING: (
        status.HTTP_409_CONFLICT,
        "This is waiting for an approval.",
        NextAction.OPEN_REQUEST,
    ),
    Reason.POLICY_DENIED: (
        status.HTTP_403_FORBIDDEN,
        "A policy refused this request.",
        NextAction.NONE,
    ),
    Reason.BUNDLE_STALE: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Enforcement is running on a cached policy.",
        NextAction.RETRY,
    ),
    Reason.INVALID_REQUEST: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The request was not valid.",
        NextAction.NONE,
    ),
    Reason.NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "That does not exist, or is not visible to you.",
        NextAction.NONE,
    ),
    Reason.CONFLICT: (
        status.HTTP_409_CONFLICT,
        "That conflicts with something that already exists.",
        NextAction.NONE,
    ),
    Reason.PRECONDITION_FAILED: (
        status.HTTP_412_PRECONDITION_FAILED,
        "Somebody else changed this while you were editing it.",
        NextAction.RETRY,
    ),
    Reason.RATE_LIMITED: (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many requests. Wait a moment and try again.",
        NextAction.RETRY,
    ),
    Reason.LICENCE_READ_ONLY: (
        status.HTTP_402_PAYMENT_REQUIRED,
        "The licence does not permit changes right now.",
        NextAction.CONTACT_OWNER,
    ),
    Reason.UPSTREAM_UNAVAILABLE: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "A service this page depends on is unavailable.",
        NextAction.RETRY,
    ),
    Reason.IDENTITY_PROVIDER_UNAVAILABLE: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "We could not reach the identity provider to check your credentials.",
        NextAction.RETRY,
    ),
    Reason.INTERNAL_ERROR: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Something failed on our side. The request id below identifies it in our logs.",
        NextAction.RETRY,
    ),
}

_UNAUTHENTICATED_CHALLENGE = 'Bearer realm="aap"'


class ApiError(Exception):
    """A refusal with a reason attached. The only way a domain should say no.

    ``status`` comes from the catalogue unless a caller overrides it, so a reason and
    its HTTP status cannot drift apart across the forty-odd routers that raise them.
    """

    def __init__(
        self,
        reason: Reason,
        *,
        message: str | None = None,
        detail: dict[str, Any] | None = None,
        next_action: NextAction | None = None,
        next_detail: dict[str, Any] | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        default_status, default_message, default_next = _CATALOGUE[reason]
        self.reason = reason
        self.message = message or default_message
        self.detail = detail or {}
        self.next_action = next_action or default_next
        self.next_detail = next_detail or {}
        self.status_code = status_code or default_status
        self.headers = dict(headers or {})
        if self.status_code == status.HTTP_401_UNAUTHORIZED:
            # RFC 6750. A 401 without this leaves a client unable to tell what to do
            # next, and one test in the suite asserts it on every protected route.
            self.headers.setdefault("WWW-Authenticate", _UNAUTHENTICATED_CHALLENGE)
        super().__init__(f"{reason}: {self.message}")

    def envelope(self) -> dict[str, Any]:
        return _envelope(
            reason=self.reason,
            message=self.message,
            detail=self.detail,
            next_action=self.next_action,
            next_detail=self.next_detail,
        )


def _envelope(
    *,
    reason: Reason,
    message: str,
    detail: dict[str, Any],
    next_action: NextAction,
    next_detail: dict[str, Any],
) -> dict[str, Any]:
    return {
        "reason": str(reason),
        "message": message,
        "detail": detail,
        "next": {"kind": str(next_action), **next_detail},
        "request_id": current_request_id(),
    }


# Status codes that arrive from un-migrated `HTTPException` raises, and the reason each
# becomes. Coarse on purpose: the point is that nothing escapes without a reason, not
# that this table is a good substitute for raising `ApiError`.
_STATUS_REASONS: dict[int, Reason] = {
    status.HTTP_400_BAD_REQUEST: Reason.INVALID_REQUEST,
    status.HTTP_401_UNAUTHORIZED: Reason.NOT_AUTHENTICATED,
    status.HTTP_402_PAYMENT_REQUIRED: Reason.LICENCE_READ_ONLY,
    status.HTTP_403_FORBIDDEN: Reason.MODULE_FORBIDDEN,
    status.HTTP_404_NOT_FOUND: Reason.NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: Reason.INVALID_REQUEST,
    status.HTTP_409_CONFLICT: Reason.CONFLICT,
    status.HTTP_412_PRECONDITION_FAILED: Reason.PRECONDITION_FAILED,
    status.HTTP_422_UNPROCESSABLE_CONTENT: Reason.INVALID_REQUEST,
    status.HTTP_429_TOO_MANY_REQUESTS: Reason.RATE_LIMITED,
    status.HTTP_502_BAD_GATEWAY: Reason.UPSTREAM_UNAVAILABLE,
    status.HTTP_503_SERVICE_UNAVAILABLE: Reason.UPSTREAM_UNAVAILABLE,
    status.HTTP_504_GATEWAY_TIMEOUT: Reason.UPSTREAM_UNAVAILABLE,
}

# A handful of routers already raise `HTTPException` whose detail *is* a reason code.
# Honouring them keeps the translation from flattening a precise refusal into a generic
# one on the way out.
_DETAIL_REASONS: dict[str, Reason] = {str(reason): reason for reason in Reason}


def _reason_for(exc: StarletteHTTPException) -> tuple[Reason, str]:
    detail = exc.detail if isinstance(exc.detail, str) else ""
    named = _DETAIL_REASONS.get(detail.strip())
    if named is not None:
        return named, _CATALOGUE[named][1]

    reason = _STATUS_REASONS.get(exc.status_code, Reason.INTERNAL_ERROR)
    # A refusal that explains itself is better than the catalogue default, but only for
    # statuses whose text is written for a person. 401 text is deliberately opaque (see
    # `app/auth/tokens.py`) and 500 text is an exception repr, so both keep the default.
    if detail and exc.status_code not in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ):
        return reason, detail
    return reason, _CATALOGUE[reason][1]


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    if exc.status_code >= 500:
        log.warning(
            "request refused", extra={"reason": str(exc.reason), "request_id": current_request_id()}
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.envelope(),
        headers={**exc.headers, REQUEST_ID_HEADER: current_request_id()},
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Wrap an un-migrated ``HTTPException`` so the console can still render it."""
    assert isinstance(exc, StarletteHTTPException)
    reason, message = _reason_for(exc)
    headers = dict(exc.headers or {})
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        headers.setdefault("WWW-Authenticate", _UNAUTHENTICATED_CHALLENGE)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(
            reason=reason,
            message=message,
            detail={},
            next_action=_CATALOGUE[reason][2],
            next_detail={},
        ),
        headers={**headers, REQUEST_ID_HEADER: current_request_id()},
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 from Pydantic. The field list is structured detail, not a sentence.

    FastAPI's own body is a bare ``{"detail": [...]}`` list, which is the one error shape
    the console cannot render at all — it has no message in it.
    """
    assert isinstance(exc, RequestValidationError)
    fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())[1:]),
            "problem": str(error.get("msg", "")),
        }
        for error in exc.errors()[:20]
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=_envelope(
            reason=Reason.INVALID_REQUEST,
            message="The request was not valid.",
            detail={"fields": fields},
            next_action=NextAction.NONE,
            next_detail={},
        ),
        headers={REQUEST_ID_HEADER: current_request_id()},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """The last resort. Logs the traceback, returns the request id and nothing else.

    An unhandled exception is the one case where the message must not describe what
    happened: the text would be an exception repr, which is both useless to the person
    reading it and a disclosure to anyone who is not.
    """
    log.exception("unhandled error", extra={"request_id": current_request_id()})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            reason=Reason.INTERNAL_ERROR,
            message=_CATALOGUE[Reason.INTERNAL_ERROR][1],
            detail={},
            next_action=NextAction.RETRY,
            next_detail={},
        ),
        headers={REQUEST_ID_HEADER: current_request_id()},
    )


_SAFE_REQUEST_ID = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _accept_inbound_request_id(value: str) -> bool:
    """A client may correlate its own id, within limits.

    This value is written to log lines and returned in an error body, so an unbounded
    caller-controlled string here is a log-injection primitive. Restricting it to a short
    alphanumeric token costs nothing and removes the question.
    """
    return 8 <= len(value) <= 64 and all(character in _SAFE_REQUEST_ID for character in value)


async def request_id_middleware(request: Request, call_next: Any) -> Any:
    incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
    request_id = incoming if _accept_inbound_request_id(incoming) else new_request_id()
    bind_request_id(request_id)
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def install_error_handling(app: FastAPI) -> None:
    """Register the request-id middleware and every handler. Called from ``create_app``.

    Order matters: the middleware has to run before any handler so the envelope has an
    id to quote. Starlette runs user middleware outside the exception middleware, which
    gives exactly that.
    """
    app.middleware("http")(request_id_middleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
