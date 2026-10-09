"""Walking the application's routes, which is no longer as simple as `app.routes`.

Two tests depend on enumerating every endpoint this application serves: the one asserting
no `/v1` route answers without a credential, and the one asserting every route holding a
database session commits before it responds. Both are written as enumerations precisely
so a router added next month is covered without anyone remembering to add it.

FastAPI 0.141 changed how that enumeration works. `include_router` used to copy each
child route onto the parent, so `app.routes` was a flat list of `APIRoute`. It now appends
a single `_IncludedRouter` holding the child router and resolves effective paths lazily.
`app.routes` on this application is consequently four docs routes, three `APIRoute` and
one opaque wrapper — so the auth test, which filtered for `APIRoute`, went from covering
47 endpoints to covering one, **and still passed**. That is the precise failure this style
of test exists to prevent.

Both representations have to be walked, because `pyproject.toml` pins `fastapi>=0.115` and
so either is a supported install. The lazy wrapper types therefore load optionally: on a
pre-0.141 FastAPI they do not exist and `app.routes` is already the flat list this walker
wants. Importing them unconditionally made collection fail outright on a supported version.

What keeps that from becoming the silent undercount described above is not the import — it
is `tests/unit/test_routes.py`, which asserts this walker finds sixty-odd routes and names
specific endpoints from opposite ends of the tree. A walker that stopped at a wrapper, on
either version, fails there loudly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

try:
    # Private, and deliberately reached for anyway: there is no public way to resolve an
    # included route's served path, and re-deriving prefix joining here is how a walker
    # ends up disagreeing with the router it describes.
    from fastapi.routing import (  # type: ignore[attr-defined]
        _EffectiveRouteContext,
        _IncludedRouter,
    )

    _LAZY_INCLUDE_TYPES: tuple[type, ...] = (_IncludedRouter,)
    _EFFECTIVE_TYPES: tuple[type, ...] = (_EffectiveRouteContext,)
except ImportError:  # FastAPI < 0.141 flattens on include_router.
    _LAZY_INCLUDE_TYPES = ()
    _EFFECTIVE_TYPES = ()


@dataclass(frozen=True)
class ResolvedRoute:
    """One endpoint, with its path as actually served rather than as declared."""

    path: str
    methods: frozenset[str]
    route: APIRoute
    dependant: Dependant
    include_in_schema: bool


def resolved_routes(app: FastAPI) -> list[ResolvedRoute]:
    """Every endpoint the app serves, with prefixes applied.

    On a FastAPI that resolves includes lazily, `_EffectiveRouteContext` already carries
    the combined path, the method set and the solved dependency tree, so nothing here
    re-derives them. On one that flattens, the route itself carries all three.
    """
    found: list[ResolvedRoute] = []
    seen: set[tuple[str, frozenset[str]]] = set()

    def remember(route: APIRoute, carrier: Any) -> None:
        """`carrier` supplies the served path and the solved dependency tree: the route
        itself for one declared on the app, the effective context for one that arrived
        through an include."""
        key = (str(carrier.path), frozenset(carrier.methods or ()))
        if key in seen:
            return
        seen.add(key)
        found.append(
            ResolvedRoute(
                path=key[0],
                methods=key[1],
                route=route,
                dependant=carrier.dependant,
                include_in_schema=carrier.include_in_schema,
            )
        )

    def walk(items: Iterable[object]) -> None:
        for item in items:
            if _LAZY_INCLUDE_TYPES and isinstance(item, _LAZY_INCLUDE_TYPES):
                walk(item.effective_candidates())
                walk(item.effective_low_priority_routes())
            elif _EFFECTIVE_TYPES and isinstance(item, _EFFECTIVE_TYPES):
                remember(item.original_route, item)
            elif isinstance(item, APIRoute):
                remember(item, item)

    walk(app.routes)
    return found


def readable_paths(app: FastAPI, prefix: str = "/v1") -> list[ResolvedRoute]:
    """The GET endpoints under `prefix`. What an unauthenticated caller would probe."""
    return [r for r in resolved_routes(app) if "GET" in r.methods and r.path.startswith(prefix)]
