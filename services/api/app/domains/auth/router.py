"""Sign in, stay signed in, sign out, and see where else you are signed in.

Two of these endpoints answer without a credential, which is unusual enough in this API
that `tests/unit/test_api_auth.py` keeps an explicit list of them. They have to: one is
how the login screen learns what to render, and the other is how a person who has no
session gets one.

The session token appears in exactly one place — a `Set-Cookie` header — and never in a
response body. A body the browser's JavaScript can read is a token its JavaScript can
leak, which is the whole reason `sessionStorage` is being taken away.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import ConsoleSession, CurrentMember, Session, VerifiedOrg
from app.api.route import TransactionalRoute
from app.config import get_settings
from app.domains.auth import service
from app.domains.auth.schemas import (
    AuthConfigOut,
    SessionListOut,
    SessionOut,
    SessionStart,
)

router = APIRouter(route_class=TransactionalRoute)


def cookie_attributes() -> dict[str, Any]:
    """The attributes on the session cookie, decided in one place.

    ``HttpOnly`` so script cannot read it. ``SameSite=Lax`` so a cross-site form post
    cannot act as the signed-in user, while an ordinary top-level navigation back from
    the identity provider still carries it — ``Strict`` would break exactly that
    redirect. ``Secure`` everywhere except a development install, where the console is
    served over plain HTTP on localhost and a ``Secure`` cookie would simply be dropped.
    """
    settings = get_settings()
    return {
        "key": settings.session_cookie_name,
        "httponly": True,
        "secure": settings.environment != "development",
        "samesite": "lax",
        "path": "/",
    }


def _client_ip(request: Request) -> str | None:
    """The peer address, not ``X-Forwarded-For``.

    A forwarded header is caller-controlled unless every hop in front of this process is
    trusted and strips it, and this deployment cannot assume that. A proxy's own address
    recorded honestly is more useful than an attacker's chosen one recorded credulously.
    """
    return request.client.host if request.client else None


@router.get(
    "/config",
    response_model=AuthConfigOut,
    summary="Which sign-in methods this deployment offers",
)
async def auth_config(
    email_domain: Annotated[str | None, Query(max_length=253)] = None,
) -> AuthConfigOut:
    """Unauthenticated by necessity: it is read before anybody can be authenticated.

    Returns no secrets. ``client_id`` and ``authorize_url`` are in the address bar of
    every sign-in that has ever happened; ``client_secret_ref``, ``token_url``,
    ``jwks_uri`` and ``claim_map`` are not in the response model at all.
    """
    return await service.config_for(email_domain)


@router.post(
    "/session",
    response_model=SessionOut,
    summary="Exchange an authorization code for a console session",
)
async def start_session(payload: SessionStart, request: Request, response: Response) -> SessionOut:
    issued = await service.start(
        payload,
        user_agent=request.headers.get("User-Agent"),
        client_ip=_client_ip(request),
    )
    response.set_cookie(
        value=issued.token,
        max_age=get_settings().session_absolute_hours * 3600,
        **cookie_attributes(),
    )
    return issued.session


@router.post(
    "/refresh",
    response_model=SessionOut,
    summary="Extend the current session",
)
async def refresh_session(active: ConsoleSession) -> SessionOut:
    """Slides the idle window forward. Never moves the absolute ceiling."""
    return await service.renew(active)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current session",
)
async def logout(active: ConsoleSession, response: Response) -> None:
    """Revokes the row first, clears the cookie second.

    That order matters if the second step fails: a revoked row with a stale cookie is a
    session that no longer works, and a live row with no cookie is a session somebody
    else's copy of the token can still use.
    """
    await service.end(active)
    response.delete_cookie(**cookie_attributes())


@router.get(
    "/sessions",
    response_model=SessionListOut,
    summary="Where you are currently signed in",
)
async def list_sessions(
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
    active: ConsoleSession,
) -> SessionListOut:
    return await service.list_for_member(session, org_id, member.member_id, current_id=active.id)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one of your own sessions",
)
async def revoke_session(
    session_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
    active: ConsoleSession,
) -> None:
    await service.revoke_for_member(
        session, org_id, member.member_id, session_id, current_id=active.id
    )
