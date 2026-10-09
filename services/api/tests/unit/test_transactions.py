"""The commit must be ordered before the response (Q-016).

The defect these tests close: `get_session` is a dependency declared with `yield`, and
its teardown resumes *after* the response has been sent. So the transaction committed
after the client had already been handed a 201, and a client that created something and
read it straight back got a 404 about half the time — including the console, and
including the end-to-end smoke run, which went pass, fail, fail on an unchanged stack.

`test_teardown_runs_after_the_response_is_sent` pins the framework behaviour that makes
this necessary rather than merely tidy. If a future FastAPI closes its exit stack
earlier, that test fails and tells us the workaround can go.

`test_every_route_that_uses_a_session_commits_before_responding` is the one that keeps it
fixed. It enumerates the application's own routes instead of naming them here, because a
list written in a test file passes while a domain added next month regresses.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from starlette.types import Receive, Scope, Send

from app.api.deps import get_session
from app.api.route import TransactionalRoute, attach_session
from tests.routes import ResolvedRoute, resolved_routes


class _Recorder:
    """Stands in for an `AsyncSession`, noting what was called on it and in what order.

    A real session is not needed and would obscure the point: what is under test is the
    sequence of calls the route class makes, not anything SQLAlchemy does.
    """

    def __init__(self, order: list[str], *, open_transaction: bool = True, fails: bool = False):
        self._order = order
        self._open = open_transaction
        self._fails = fails

    def in_transaction(self) -> bool:
        return self._open

    async def commit(self) -> None:
        self._order.append("commit")
        self._open = False
        if self._fails:
            raise RuntimeError("deferred constraint violated on commit")


def _app_recording(order: list[str], recorder: _Recorder) -> Any:
    """A one-route app whose session is `recorder`, wrapped to log every ASGI send.

    The wrapper is what makes ordering observable. `httpx` only returns once the response
    is complete, so without capturing `http.response.start` there is nothing to compare
    the commit against.
    """
    app = FastAPI()
    router = APIRouter(route_class=TransactionalRoute)

    async def session_for_request(request: Request) -> AsyncIterator[_Recorder]:
        attach_session(request, cast("Any", recorder))
        yield recorder
        order.append("teardown")

    # `Depends` goes in the default, not inside `Annotated`. This module has
    # `from __future__ import annotations`, so annotations are strings that FastAPI
    # resolves against the module's globals — and `session_for_request` is a local of
    # this function, so it is not resolvable there. The annotated form therefore failed
    # to resolve and FastAPI fell back to treating the parameter as a query string
    # field, answering 422 before the handler ever ran. The default is a real object
    # evaluated at definition time, so it is immune to that.
    @router.get("/thing")
    async def thing(session: _Recorder = Depends(session_for_request)) -> dict[str, bool]:
        assert session is recorder
        order.append("handler")
        return {"ok": True}

    app.include_router(router)

    async def recording(scope: Scope, receive: Receive, send: Send) -> None:
        async def note(message: Any) -> None:
            order.append(str(message["type"]))
            await send(message)

        await app(scope, receive, note)

    return recording


async def _get(app: Any, *, raise_app_exceptions: bool = True) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get("/thing")


@pytest.mark.asyncio
async def test_the_commit_is_ordered_before_the_response_is_sent() -> None:
    order: list[str] = []
    response = await _get(_app_recording(order, _Recorder(order)))

    assert response.status_code == 200, response.text
    assert "commit" in order, order
    assert order.index("handler") < order.index("commit"), order
    assert order.index("commit") < order.index("http.response.start"), order


@pytest.mark.asyncio
async def test_teardown_runs_after_the_response_is_sent() -> None:
    """The whole of Q-016, as an assertion.

    This is framework behaviour, not ours: FastAPI holds the dependency exit stack in the
    request scope from a middleware outside the router, so teardown cannot precede the
    response. A commit left there is a commit the client was already told about. If this
    ever fails, `TransactionalRoute` is no longer needed.
    """
    order: list[str] = []
    await _get(_app_recording(order, _Recorder(order)))

    assert order.index("http.response.start") < order.index("teardown"), order


@pytest.mark.asyncio
async def test_a_session_already_out_of_its_transaction_is_not_committed_again() -> None:
    """Committing twice raises, because the first commit closed the transaction. This is
    why the route class asks before acting, and why `tenant_session` does too."""
    order: list[str] = []
    response = await _get(_app_recording(order, _Recorder(order, open_transaction=False)))

    assert response.status_code == 200, response.text
    assert "commit" not in order, order


@pytest.mark.asyncio
async def test_a_failed_commit_is_not_reported_as_success() -> None:
    """The quieter half of the bug. A commit that failed in teardown failed after the 201
    had gone out, so the client was told a row existed that never did."""
    order: list[str] = []

    app = _app_recording(order, _Recorder(order, fails=True))
    response = await _get(app, raise_app_exceptions=False)

    assert response.status_code == 500, response.text
    assert "http.response.start" not in order[: order.index("commit")], order


def _uses_session(dependant: Dependant) -> bool:
    """Whether `get_session` appears anywhere in this route's dependency tree.

    Walked explicitly rather than through `get_flat_dependant`, which merges parameters
    but is not a documented way to ask this question.
    """
    seen: set[int] = set()
    stack = [dependant]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if current.call is get_session:
            return True
        stack.extend(current.dependencies)
    return False


def _routes() -> list[ResolvedRoute]:
    from app.main import create_app

    return resolved_routes(create_app())


def test_every_route_that_uses_a_session_commits_before_responding() -> None:
    """Enumerated from the app, so a new domain router fails this rather than shipping
    with the bug. The route class has to be declared on each domain router: FastAPI keeps
    the included router as-is, so a class set on the aggregate router never reaches it.
    """
    plain = [
        f"{sorted(r.methods)} {r.path}"
        for r in _routes()
        if _uses_session(r.dependant) and not isinstance(r.route, TransactionalRoute)
    ]

    assert plain == [], f"routes that commit in teardown rather than before responding: {plain}"


def test_the_route_list_is_not_empty() -> None:
    """Guards the test above: a bug in `_uses_session` that matched nothing would make it
    pass by covering no route at all."""
    using = [r for r in _routes() if _uses_session(r.dependant)]

    assert len(using) > 40, len(using)
