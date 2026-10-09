"""The route class every domain router uses, and the reason it has to exist.

A dependency declared with ``yield`` resumes *after* its handler returns, and on FastAPI
0.141 the exit stack that drives that resumption is held in the request scope by a
middleware sitting outside the router. So the commit at the end of ``get_session`` ran
after the response had already been handed back to Starlette to send. A client that
created something and read it straight back therefore raced the commit and saw a 404
about half the time — and the console does exactly that, as did the smoke run (Q-016).

Starlette's ``request_response`` awaits the route handler to completion before it sends
anything, which makes this class the innermost place in the request still guaranteed to
precede the response. Committing here orders the write ahead of the first byte.

It closes a quieter bug at the same time. A commit that *fails* in teardown fails after a
201 has already gone out, so the client is told a row exists that never did. Raising from
here instead reaches the exception middleware and becomes a 500, which is the truth.

Every domain router passes ``route_class=TransactionalRoute``, because FastAPI's
``include_router`` re-creates each route as ``type(route)`` — setting it once on the
aggregate router in ``app/api/v1/router.py`` would not reach the domains. It has to be
declared where the router is built. ``tests/unit/test_transactions.py`` enumerates the
application's own routes and fails if one that depends on a session is a plain
``APIRoute``, so a domain added next month cannot quietly opt out of this.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

# One place owns the attribute name. `deps.get_session` writes it, this module reads it,
# and nothing else should touch it.
_STATE_ATTR = "tenant_session"


def attach_session(request: Request, session: AsyncSession) -> None:
    """Park the request's session where :class:`TransactionalRoute` can commit it."""
    request.state.tenant_session = session


def attached_session(request: Request) -> AsyncSession | None:
    """The session for this request, or ``None`` for a handler that needs no database."""
    return getattr(request.state, _STATE_ATTR, None)


class TransactionalRoute(APIRoute):
    """Commits the request's transaction before its response is sent."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def commit_then_respond(request: Request) -> Response:
            response = await handle(request)

            session = attached_session(request)
            if session is not None and session.in_transaction():
                # Reads commit too. A read transaction holds its snapshot open until it
                # ends, and ending it here rather than in teardown means one rule for
                # every handler instead of one rule per HTTP method.
                await session.commit()

            return response

        return commit_then_respond
