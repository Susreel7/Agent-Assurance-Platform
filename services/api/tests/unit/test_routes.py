"""The route walker has to be right, because two invariants are built on it.

`tests/routes.py` reaches into FastAPI internals. That is a considered trade — the
alternative is a hand-kept list of endpoints, which is the thing the tests built on this
were written to avoid — but it means the walker itself needs holding in place.

The failure mode being guarded is specific and has already happened once. When FastAPI
0.141 stopped flattening `include_router`, the auth test's enumeration silently collapsed
from 47 endpoints to 1 and carried on passing. A test that asserts "nothing is unguarded"
across an empty set is worse than no test, because it reports confidence it does not have.
"""

from __future__ import annotations

from fastapi import FastAPI

from tests.routes import readable_paths, resolved_routes


def _app() -> FastAPI:
    from app.main import create_app

    app = create_app()
    assert isinstance(app, FastAPI)
    return app


def test_the_walker_finds_the_whole_api_not_just_the_top_level() -> None:
    """`app.routes` holds eight entries; the application serves an order of magnitude
    more. Anything near eight means the walker stopped at the wrapper again."""
    routes = resolved_routes(_app())

    assert len(routes) > 60, f"walker found only {len(routes)} routes: {[r.path for r in routes]}"


def test_known_endpoints_are_reachable_through_the_walker() -> None:
    """Named endpoints from opposite ends of the router tree, so a walker that finds the
    first included router but not nested ones fails here."""
    paths = {r.path for r in resolved_routes(_app())}

    for expected in (
        "/healthz",
        "/v1/agents",
        "/v1/agents/{agent_id}",
        "/v1/releases/preview",
        "/v1/home/summary",
        "/v1/portal/{customer_slug}/{engagement_slug}",
    ):
        assert expected in paths, f"{expected} missing; walker found {sorted(paths)}"


def test_prefixes_are_applied() -> None:
    """A route declared as `/{agent_id}` on the registry router is served at
    `/v1/agents/{agent_id}`. Returning the declared path would make every path-based
    assertion built on this quietly wrong."""
    paths = {r.path for r in resolved_routes(_app())}

    assert "/{agent_id}" not in paths
    assert not any(p for p in paths if not p.startswith("/")), sorted(paths)


def test_readable_paths_are_get_endpoints_under_the_prefix() -> None:
    readable = readable_paths(_app())

    assert len(readable) > 25, len(readable)
    assert all("GET" in r.methods for r in readable)
    assert all(r.path.startswith("/v1") for r in readable)


def test_every_route_carries_a_dependency_tree() -> None:
    """The transaction test walks `dependant` to find routes that use a session. A
    `None` there would make it find nothing and pass."""
    assert all(r.dependant is not None for r in resolved_routes(_app()))
