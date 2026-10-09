"""Call every readable route on a running API and report what breaks.

This exists because a 500 reached the user from a route no test touched. The failure was
`column c.name does not exist` — raw SQL naming a column that had been called
`display_name` since the first migration. Nothing caught it: unit tests do not open a
connection, the integration tests cover repositories the suite happens to exercise, and
the schema-drift test compares ORM models to Postgres while that query is a text() blob
the ORM never sees.

So the check is the crude one, and crude is the point: ask the API for its own route list,
call all of it, and report the status codes. It finds precisely the class of bug that
slips past typed tests — a route that is wired up, returns 200 in nobody's test, and
raises the moment a real row goes through it.

Read-only by default. `--post` additionally calls POST routes whose names read as
computations rather than state changes, which is how `/assess` and `/verify` get covered;
anything that transitions a release or seals a batch stays out unless asked for by name.

    docker compose exec api python -m tests.smoke.sweep
    docker compose exec api python -m tests.smoke.sweep --post

**Not migrated to console sessions (F0).** This harness authenticates by sending an
`X-Org-Id` header under the old development bypass. Both are gone: `X-Org-Id` was never
a credential and the bypass was replaced by a `development` row in `auth_providers`, so
every request this makes now returns 401. Fixing it means signing in through
`POST /v1/auth/session` and carrying the session cookie, which is a change to the
harness rather than to the API and was deliberately left for a slice that can run it —
this one had no database or container runtime available to verify against.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE = os.environ.get("AAP_SMOKE_BASE", "http://localhost:8000")

# Path parameters are filled from whatever the list endpoints return, because an id
# invented here would exercise the 404 branch and prove nothing. Each entry says: to
# learn a value for this parameter, read this route and take this field.
#
# The list endpoints themselves need no parameters, which is what makes the two passes
# work — harvest first, then substitute.
PARAM_SOURCES: dict[str, tuple[str, str]] = {
    "agent_id": ("/v1/agents", "id"),
    "version_id": ("/v1/agents", "current_version_id"),
    "release_id": ("/v1/releases", "id"),
    "customer_id": ("/v1/customers", "id"),
    "customer_slug": ("/v1/customers", "slug"),
    "engagement_id": ("/v1/engagements", "id"),
    "engagement_slug": ("/v1/engagements", "slug"),
    "accreditation_id": ("/v1/accreditations", "id"),
    "finding_id": ("/v1/assurance/findings", "id"),
    "slo_id": ("/v1/slos", "id"),
    "node_id": ("/v1/graph/nodes", "id"),
    "event_id": ("/v1/evidence", "id"),
    "policy_id": ("/v1/policies", "id"),
    "framework_id": ("/v1/frameworks", "id"),
    "run_id": ("/v1/operations/runs", "id"),
}

# A parameter name does not always mean the same thing in two domains. `run_id` is an
# agent run under /v1/operations and a probe run under /v1/assurance, and filling one
# with the other produces a 404 that reads like a broken route. Longest matching prefix
# wins, so these override the table above.
PARAM_SOURCES_BY_PREFIX: dict[str, dict[str, tuple[str, str]]] = {
    "/v1/assurance/probe-runs": {"run_id": ("/v1/assurance/probe-runs", "id")},
}

# POST routes that compute and return rather than transition something. Named explicitly
# rather than matched by pattern: the cost of wrongly including a state change here is a
# corrupted demo estate, and the cost of omitting one is a route left unswept.
SAFE_POSTS = {
    "/v1/materiality/releases/{release_id}/assess",
    "/v1/releases/preview/review-brief",
}

# Routes whose 4xx is the correct answer to a request with no body or no real subject.
# Reported separately so they do not read as passes or as failures.
EXPECTED_4XX = {422, 400}


@dataclass
class Result:
    method: str
    path: str
    url: str
    status: int | None
    detail: str = ""
    skipped_param: str = ""


@dataclass
class Harvest:
    """Values learned from list endpoints, keyed by path-parameter name."""

    values: dict[str, str] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def record(self, param: str, value: str) -> None:
        self.values.setdefault(param, value)


def first_id(body: object, field_name: str) -> str | None:
    """Pull one identifier out of a list response, page or bare array."""
    items = body.get("items") if isinstance(body, dict) else body
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict):
            value = item.get(field_name)
            if isinstance(value, str) and value:
                return value
    return None


async def harvest(client: httpx.AsyncClient) -> Harvest:
    """Learn one real value per parameter, under both its plain and prefixed key."""
    out = Harvest()
    wanted: list[tuple[str, str, str]] = [
        (param, route, field_name) for param, (route, field_name) in PARAM_SOURCES.items()
    ]
    for prefix, overrides in PARAM_SOURCES_BY_PREFIX.items():
        for param, (route, field_name) in overrides.items():
            wanted.append((f"{prefix}#{param}", route, field_name))

    for key, route, field_name in wanted:
        try:
            res = await client.get(route, params={"limit": "5"})
        except httpx.HTTPError as exc:
            out.failures.append(f"{key}: {route} raised {type(exc).__name__}")
            continue
        if res.status_code != 200:
            out.failures.append(f"{key}: {route} returned {res.status_code}")
            continue
        value = first_id(res.json(), field_name)
        if value is None:
            out.failures.append(f"{key}: {route} returned no usable {field_name}")
            continue
        out.record(key, value)
    return out


def resolve(param: str, path: str, known: dict[str, str]) -> str | None:
    """Prefer a value harvested for this path's domain over the generic one."""
    matches = sorted(
        (p for p in PARAM_SOURCES_BY_PREFIX if path.startswith(p)), key=len, reverse=True
    )
    for prefix in matches:
        value = known.get(f"{prefix}#{param}")
        if value:
            return value
    return known.get(param)


def fill(path: str, known: dict[str, str]) -> tuple[str, str]:
    """Substitute path parameters. Returns (url, missing_param_name)."""
    missing = ""

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        name = match.group(1)
        value = resolve(name, path, known)
        if value is not None:
            return value
        missing = missing or name
        return match.group(0)

    return re.sub(r"\{([^}]+)\}", replace, path), missing


async def sweep(base: str, include_posts: bool) -> int:
    org_id = os.environ.get("AAP_SMOKE_ORG_ID", "")
    headers = {"X-Org-Id": org_id} if org_id else {}

    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=60.0) as client:
        spec = (await client.get("/openapi.json")).json()

        # Without a tenant every request is a 403 and the sweep proves nothing, so
        # resolve one from the estate rather than requiring it to be passed in.
        if not org_id:
            res = await client.get("/v1/agents", params={"limit": "1"})
            if res.status_code == 403:
                print(
                    "No org id. Pass AAP_SMOKE_ORG_ID, or run where dev auth bypass is on.",
                    file=sys.stderr,
                )
                return 2

        learned = await harvest(client)
        if learned.failures:
            print("Could not learn every path parameter:")
            for f in learned.failures:
                print(f"  {f}")
            print()

        results: list[Result] = []
        for path, operations in sorted(spec.get("paths", {}).items()):
            for method, operation in operations.items():
                method = method.upper()
                if method == "GET" or (method == "POST" and include_posts and path in SAFE_POSTS):
                    pass
                else:
                    continue

                url, missing = fill(path, learned.values)
                if missing:
                    results.append(Result(method, path, url, None, skipped_param=missing))
                    continue

                # Keep responses small: these routes are being called for their status
                # code, not their contents, and some pages are large.
                params = {}
                for p in operation.get("parameters", []):
                    if p.get("in") == "query" and p.get("name") == "limit":
                        params["limit"] = "5"

                try:
                    res = await client.request(method, url, params=params)
                except httpx.HTTPError as exc:
                    results.append(Result(method, path, url, None, detail=repr(exc)))
                    continue

                detail = ""
                if res.status_code >= 400:
                    body = res.text[:300].replace("\n", " ")
                    detail = body
                results.append(Result(method, path, url, res.status_code, detail))

    buckets: dict[str, list[Result]] = defaultdict(list)
    for r in results:
        if r.status is None and r.skipped_param:
            buckets["skipped"].append(r)
        elif r.status is None:
            buckets["error"].append(r)
        elif r.status >= 500:
            buckets["server_error"].append(r)
        elif r.status == 404:
            buckets["not_found"].append(r)
        elif r.status in EXPECTED_4XX:
            buckets["needs_input"].append(r)
        elif r.status >= 400:
            buckets["client_error"].append(r)
        else:
            buckets["ok"].append(r)

    def show(key: str, title: str) -> None:
        rows = buckets.get(key, [])
        if not rows:
            return
        print(f"\n{title} ({len(rows)})")
        for r in rows:
            if r.skipped_param:
                print(f"  {r.method:4} {r.path}  — no {r.skipped_param} available")
            else:
                status = r.status if r.status is not None else "EXC"
                line = f"  {status!s:4} {r.method:4} {r.path}"
                print(line if not r.detail else f"{line}\n         {r.detail}")

    print(f"Swept {len(results)} routes against {base}")
    show("server_error", "SERVER ERRORS — these are bugs")
    show("error", "TRANSPORT FAILURES")
    show("not_found", "404 — route exists but the subject did not")
    show("client_error", "OTHER 4xx")
    show("needs_input", "4xx expected without a body")
    show("skipped", "Skipped, no identifier available")
    print(f"\nOK: {len(buckets.get('ok', []))}")

    # Only server errors fail the sweep. A 404 on a route whose subject the estate does
    # not contain is a gap in the seed data, not a defect in the route.
    broken = len(buckets.get("server_error", [])) + len(buckets.get("error", []))
    if broken:
        print(f"FAILED: {broken} route(s) returned a server error or could not be reached.")
    return 1 if broken else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument(
        "--post",
        action="store_true",
        help="also call the POST routes listed in SAFE_POSTS",
    )
    args = parser.parse_args()
    return asyncio.run(sweep(args.base, args.post))


if __name__ == "__main__":
    raise SystemExit(main())
