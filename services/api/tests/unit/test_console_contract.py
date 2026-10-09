"""The F0 console-contract invariants that do not need a database.

Three of the five named invariants in `design/prompts/f0-console-contract.md` are
properties of the API's behaviour and are asserted here:

``inv_every_error_has_reason``          every error response carries a reason code
``inv_dev_provider_requires_dev_mode``  the development provider is refused outside development
``inv_no_session_without_member``       the HTTP half — a refused sign-in sets no cookie

The other two are properties of the web source tree and live in
`services/web/scripts/check-runtime-contract.mjs`, which the build runs:
``inv_no_build_time_auth`` and ``inv_bootstrap_is_single_request``.

The database half of ``inv_no_session_without_member`` — that no ``auth_sessions`` row
is written — is in `tests/integration/test_auth_sessions.py`, because proving a row does
not exist requires a real table.
"""

from __future__ import annotations

import functools
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.api.errors import _CATALOGUE, NextAction, Reason
from app.auth import providers
from app.config import get_settings
from tests.routes import readable_paths

_PLACEHOLDER = "00000000-0000-0000-0000-000000000001"

# Answers without a credential, so an unauthenticated sweep produces no error from it to
# inspect. `test_api_auth.py` owns the argument for why each one is allowed to be open;
# this file only needs to know which they are.
OPEN_PATHS = {"/v1/", "/v1/auth/config", "/healthz", "/readyz"}


@functools.lru_cache(maxsize=1)
def _app() -> Any:
    from app.main import create_app

    return create_app()


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """No lifespan, so no database. Every request here is refused before one is needed."""
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _error_paths() -> list[str]:
    return sorted(
        {
            re.sub(r"\{[^}]+\}", _PLACEHOLDER, route.path)
            for route in readable_paths(_app())
            if route.path not in OPEN_PATHS
        }
    )


def assert_is_envelope(body: object, status_code: int) -> None:
    """The five fields, every one of them, with a reason from the closed vocabulary."""
    assert isinstance(body, dict), body

    missing = {"reason", "message", "detail", "next", "request_id"} - set(body)
    assert not missing, f"error body is missing {sorted(missing)}: {body}"

    assert body["reason"] in {str(reason) for reason in Reason}, (
        f"reason {body['reason']!r} is not in the taxonomy"
    )
    # A reason with no sentence is a reason the console renders as a blank box.
    assert isinstance(body["message"], str) and body["message"].strip(), body
    assert isinstance(body["detail"], dict), body
    assert body["next"]["kind"] in {str(action) for action in NextAction}, body
    assert isinstance(body["request_id"], str) and body["request_id"], body

    # The status the reason declares, so a caller may branch on either and get the same
    # answer. Skipped for the coarse `HTTPException` translation, which keeps the
    # route's own status and picks a reason to match rather than the other way round.
    declared = _CATALOGUE[Reason(body["reason"])][0]
    assert status_code == declared or body["reason"] in {
        str(Reason.MODULE_FORBIDDEN),
        str(Reason.NOT_FOUND),
        str(Reason.INVALID_REQUEST),
        str(Reason.CONFLICT),
        str(Reason.UPSTREAM_UNAVAILABLE),
        str(Reason.NOT_AUTHENTICATED),
    }, f"status {status_code} disagrees with reason {body['reason']} ({declared})"


# --------------------------------------------------------------------------------------
# inv_every_error_has_reason
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _error_paths())
async def test_inv_every_error_has_reason(client: httpx.AsyncClient, path: str) -> None:
    """Every route's refusal is renderable.

    Unauthenticated is the one error reachable on every route without a database, which
    makes it the only sweep that can cover all of them. That is enough for what this
    guards: the envelope is produced by exception handlers registered once, so a route
    that carries a reason here carries one for every other failure too. What it catches
    is a router mounted outside `create_app`, or a handler that builds its own
    `JSONResponse` and bypasses them.
    """
    response = await client.get(path)

    assert response.status_code >= 400, f"{path} answered {response.status_code}"
    assert_is_envelope(response.json(), response.status_code)
    assert response.headers.get("X-Request-Id"), "no request id to quote in a support call"


@pytest.mark.asyncio
async def test_inv_every_error_has_reason_for_a_bad_body(client: httpx.AsyncClient) -> None:
    """422 from Pydantic used to be the one error shape with no message in it at all.

    FastAPI's default is a bare `{"detail": [...]}` list of validation objects, which the
    console cannot render as a sentence, so it fell through to "Something went wrong".
    """
    response = await client.post("/v1/auth/session", json={"provider_id": "not-a-uuid"})

    assert response.status_code == 422
    body = response.json()
    assert_is_envelope(body, response.status_code)
    assert body["reason"] == "invalid_request"
    # Structured, so the console can put the message under the field it belongs to.
    assert body["detail"]["fields"], body


@pytest.mark.asyncio
async def test_inv_every_error_has_reason_for_an_unknown_path(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/no-such-thing")

    assert response.status_code == 404
    assert_is_envelope(response.json(), response.status_code)


# --------------------------------------------------------------------------------------
# inv_dev_provider_requires_dev_mode
# --------------------------------------------------------------------------------------


def development_provider() -> providers.ProviderRecord:
    """A development row as migration 0022 seeds it.

    `localhost` deliberately — never a customer's domain and never an employer's. A
    development fixture that signs in `someone@realcompany.com` produces audit rows
    naming a real organisation for activity that never happened there.
    """
    return providers.ProviderRecord(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        kind="development",
        label="Development sign-in",
        issuer=None,
        client_id=None,
        client_secret_ref=None,
        jwks_uri=None,
        authorize_url=None,
        token_url=None,
        scopes="openid profile email",
        claim_map={},
        email_domains=["localhost"],
        onboarding_mode="jit",
        require_mfa_claim=False,
        enabled=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["production", "staging", "test", ""])
async def test_inv_dev_provider_requires_dev_mode(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    """The replacement for `Bearer dev.<email>` must be refused everywhere that was.

    Parametrised over several environments rather than just production because the old
    bypass was a boolean an operator could set anywhere. This one is not configurable at
    all: the only environment that enables it is the literal string `development`.
    """
    monkeypatch.setenv("AAP_ENVIRONMENT", environment)
    get_settings.cache_clear()

    with pytest.raises(providers.ProviderError) as raised:
        await providers.verify(
            development_provider(),
            code=None,
            code_verifier=None,
            redirect_uri=None,
            nonce=None,
            development_email="someone@localhost",
        )

    assert raised.value.reason is Reason.PROVIDER_DISABLED
    assert _CATALOGUE[raised.value.reason][0] == 403
    assert not providers.development_mode_enabled()


@pytest.mark.asyncio
async def test_the_development_provider_works_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half. A refusal that also refused in development would be a bypass
    nobody could use, and somebody would put the old one back."""
    monkeypatch.setenv("AAP_ENVIRONMENT", "development")
    get_settings.cache_clear()

    resolved = await providers.verify(
        development_provider(),
        code=None,
        code_verifier=None,
        redirect_uri=None,
        nonce=None,
        development_email="Someone@LOCALHOST",
    )

    assert resolved.email == "someone@localhost"
    assert resolved.subject == "dev:someone@localhost"
    # Never a real issuer value, so an audit row from a development session can always
    # be told apart from a production one.
    assert resolved.issuer == providers.DEVELOPMENT_ISSUER


@pytest.mark.asyncio
async def test_the_development_provider_refuses_a_domain_it_does_not_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AAP_ENVIRONMENT", "development")
    get_settings.cache_clear()

    with pytest.raises(providers.ProviderError) as raised:
        await providers.verify(
            development_provider(),
            code=None,
            code_verifier=None,
            redirect_uri=None,
            nonce=None,
            development_email="someone@a-real-company.com",
        )

    assert raised.value.reason is Reason.NOT_PROVISIONED


# --------------------------------------------------------------------------------------
# inv_no_session_without_member (the half that needs no database)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"provider_id": "not-a-uuid"},
        {"provider_id": str(uuid.uuid4()), "code": ""},
    ],
)
async def test_inv_no_session_without_member_sets_no_cookie(
    client: httpx.AsyncClient, payload: dict[str, str]
) -> None:
    """A sign-in that did not succeed must leave the browser holding nothing.

    A cookie set alongside a failure is worse than no cookie: the console would believe
    it had a session, send it, and be refused on the next request with an error
    describing the *second* problem rather than the first. That is the shape of the bug
    this phase exists to remove.

    These payloads are refused before a database is consulted, which is what keeps this
    a unit test. The cases that get further — a real provider whose verification fails,
    a person nobody invited — are in `tests/integration/test_auth_sessions.py`, where
    there is a table to prove no row was written to.
    """
    response = await client.post("/v1/auth/session", json=payload)

    assert response.status_code >= 400, response.text
    assert "set-cookie" not in {name.lower() for name in response.headers}, response.headers
    assert_is_envelope(response.json(), response.status_code)
