"""Every v1 endpoint is behind a token, and the ops endpoints are not.

This is the test that would have failed before `app/auth` existed, when the organisation
came from a header any caller could set. It goes through the ASGI app rather than calling
`resolve_org` directly, because what matters is the wiring: a router that forgot to depend
on the session, or a dependency added in the wrong order, is invisible to a unit test of
the dependency itself.

No database is involved. Authentication resolves before the session dependency, so a
request without a credential is refused before anything is queried — which is both the
security property and the reason these run as unit tests.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.auth import jwks
from app.config import get_settings
from tests.routes import readable_paths

OPEN = ["/healthz", "/readyz"]

# Routes allowed to answer without a credential, each for a stated reason. Adding to
# this list is the decision; the test below only enforces it. Everything reported by
# these is already public or already in `/readyz`.
DELIBERATELY_OPEN = {
    "/v1/": "a static index naming the docs url, with no data in it",
    "/v1/auth/config": (
        "the login screen reads it before anybody is signed in — that is the point of "
        "it. Returns labels and authorize URLs, never a client secret, and hides the "
        "development provider outside development"
    ),
}

_PLACEHOLDER = "00000000-0000-0000-0000-000000000001"


def protected_paths() -> list[str]:
    """Every readable `/v1` path, taken from the app rather than written out here.

    A hand-kept list is the wrong shape for this test: it passes while a router added
    next month sits unguarded. Two endpoints were in fact found unauthenticated the first
    time this ran. Path parameters get a placeholder because these requests are expected
    to be refused before anything looks at them.

    Routes come from `tests.routes` rather than `app.routes`. FastAPI 0.141 stopped
    flattening `include_router`, so filtering `app.routes` for `APIRoute` matched only
    the three endpoints declared directly on the app — this test covered one path for a
    while and kept passing. See the module docstring there.
    """
    paths = [
        re.sub(r"\{[^}]+\}", _PLACEHOLDER, route.path)
        for route in readable_paths(_app())
        if route.path not in DELIBERATELY_OPEN
    ]
    return sorted(set(paths))


ISSUER = "https://idp.test.example"


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve an empty key set in-process.

    Without this the tests that do send a token attempt real DNS for a `.example` name
    and wait for it to fail, which is both slow and dependent on the resolver. An empty
    set is the right stub here: every token in this file is supposed to be rejected, and
    none of them should get as far as needing a key that exists.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/keys"})
        return httpx.Response(200, json={"keys": []})

    monkeypatch.setattr(
        jwks, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


@pytest.fixture
def issuer_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    monkeypatch.setenv("AAP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("AAP_OIDC_AUDIENCE", "aap-api")
    get_settings.cache_clear()
    jwks.reset_cache()
    yield
    get_settings.cache_clear()
    jwks.reset_cache()


@functools.lru_cache(maxsize=1)
def _app() -> Any:
    """Built once for the whole file.

    Rebuilding it per test cost about two and a half seconds each, which turned this
    file into a six-minute run. Sharing it is safe because nothing here mutates the app:
    the settings that vary between tests are read per request by the auth dependency,
    not captured at construction.
    """
    from app.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(issuer_configured: None) -> AsyncIterator[httpx.AsyncClient]:
    """An in-process client with no lifespan.

    The lifespan hook connects to the database and checks the migration revision. Not
    running it is the point: these requests must never get far enough to need it.
    """
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("path", protected_paths())
async def test_a_request_without_a_token_is_refused(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 401, response.text
    # RFC 6750: a 401 without this header leaves a client unable to tell what to do next.
    assert response.headers.get("WWW-Authenticate", "").startswith("Bearer")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", protected_paths())
async def test_an_org_header_alone_is_no_longer_a_credential(
    client: httpx.AsyncClient, path: str
) -> None:
    """The defect this closes. `X-Org-Id` used to be the whole of tenant resolution, so
    any caller could read any tenant by guessing a UUID."""
    response = await client.get(path, headers={"X-Org-Id": "7b2a6037-6cf4-41ce-89ae-27d6a375a357"})

    assert response.status_code == 401, response.text


def test_the_route_list_is_not_empty() -> None:
    """Guards the two tests above: a bug in `protected_paths` that returned nothing
    would make them pass by covering no endpoint at all."""
    paths = protected_paths()
    assert len(paths) > 20, paths


@pytest.mark.asyncio
async def test_only_the_listed_routes_answer_without_a_credential(
    client: httpx.AsyncClient,
) -> None:
    """The inverse of the test above, and the one that keeps it honest.

    `protected_paths` skips `DELIBERATELY_OPEN`, so without this a new unauthenticated
    endpoint could be waved through by adding it to that set. Here the set has to be
    small and each entry has to carry its reason.
    """
    unguarded: list[str] = []
    for route in readable_paths(_app()):
        response = await client.get(re.sub(r"\{[^}]+\}", _PLACEHOLDER, route.path))
        if response.status_code != 401:
            unguarded.append(route.path)

    # Compared as sets: the assertion is about *which* routes are open, and route
    # registration order is not something this test has an opinion on.
    assert set(unguarded) == set(DELIBERATELY_OPEN), (
        f"routes answering without a credential: {sorted(unguarded)}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", OPEN)
async def test_ops_endpoints_stay_open(client: httpx.AsyncClient, path: str) -> None:
    """Orchestrator probes carry no token, and the console reads `/readyz` before login
    to discover whether the install is multi-tenant."""
    response = await client.get(path)

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_a_garbage_token_is_refused_without_reaching_the_database(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/agents", headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401, response.text


MACHINE_CREDENTIALS = [None, "Bearer garbage", "Bearer aap_wk_not-a-valid-credential"]

RUN_INGEST = (
    "/v1/operations/runs",
    {
        "runs": [
            {
                "agent_urn": "urn:aap:test:reporter",
                "environment": "production",
                "started_at": "2026-09-15T00:00:00Z",
            }
        ]
    },
)

SCORE_INGEST = (
    "/v1/evaluate/workload/scores",
    {
        "target_type": "trace",
        "target_id": "trace-1",
        "name": "quality",
        "value_type": "numeric",
        "value_numeric": 0.5,
        "source": "automated",
    },
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "body"), [RUN_INGEST, SCORE_INGEST], ids=["runs", "scores"])
async def test_machine_ingest_gives_one_generic_rejection(
    client: httpx.AsyncClient, path: str, body: dict[str, Any]
) -> None:
    """Absent, malformed and unrecognised credentials must be indistinguishable.

    Asserted by comparing the three responses to each other rather than to a literal
    string, which is the property the name claims and the literal never checked: two of
    these could have drifted apart and the test would still have passed as long as
    somebody updated the constant. The envelope makes the comparison stricter than it
    used to be, because `reason` is now something a prober could tell apart too.
    """
    envelopes = []
    for authorization in MACHINE_CREDENTIALS:
        headers = {"Authorization": authorization} if authorization is not None else {}
        response = await client.post(path, headers=headers, json=body)

        assert response.status_code == 401, response.text
        envelope = response.json()
        assert envelope["reason"] == "invalid_credential"
        # The request id differs per request by design; everything else must not.
        envelopes.append({k: v for k, v in envelope.items() if k != "request_id"})

    assert envelopes[0] == envelopes[1] == envelopes[2], (
        f"the rejection differs by credential shape: {envelopes}"
    )


@pytest.mark.asyncio
async def test_the_rejection_does_not_explain_which_check_failed(
    client: httpx.AsyncClient,
) -> None:
    """Telling an unauthenticated caller whether the issuer, audience or signature was
    wrong maps out the configuration for them."""
    response = await client.get("/v1/agents", headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401
    body = response.json()
    # The whole envelope, not just the message: `detail` is structured context and a
    # future contributor adding `{"problem": str(exc)}` there would reopen this.
    text = json.dumps(body).lower()
    for leak in ("issuer", "audience", "signature", "expired", "jwks", ISSUER):
        assert leak not in text, f"rejection leaks {leak!r}: {text}"


@pytest.mark.asyncio
async def test_no_issuer_reports_a_server_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An install that was never configured for auth must not look like bad credentials,
    or an operator debugging it is sent to look at their identity provider.

    It must equally not serve the request. This is the state a fresh deployment boots
    into, and `Settings` already logs a warning about it.
    """
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    monkeypatch.delenv("AAP_OIDC_ISSUER", raising=False)
    get_settings.cache_clear()
    jwks.reset_cache()

    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        response = await c.get("/v1/agents", headers={"Authorization": "Bearer whatever"})

    assert response.status_code == 503, response.text

    get_settings.cache_clear()
    jwks.reset_cache()
