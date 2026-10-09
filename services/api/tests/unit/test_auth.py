"""Token verification, key handling and principal derivation.

Most of this file is negative tests, which is the point: the failure mode of an auth
module is not "it rejects a good token", it is "it accepts a bad one". Each rejection
below names the attack it prevents rather than the check it exercises.

Tokens are minted here with a throwaway key rather than recorded from a provider, so the
tests cover our verification rather than one vendor's token format.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import jwks, principal, tokens
from app.config import get_settings

ISSUER = "https://idp.test.example"
AUDIENCE = "aap-api"
KID = "test-key-1"


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def jwks_document(signing_key: ec.EllipticCurvePrivateKey) -> dict[str, Any]:
    """Per-test, because the rotation tests rewrite it in place. Key generation is the
    slow part and stays module-scoped above."""
    public_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(signing_key.public_key()))
    public_jwk.update({"kid": KID, "use": "sig", "alg": "ES256"})
    return {"keys": [public_jwk]}


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    monkeypatch.setenv("AAP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("AAP_OIDC_AUDIENCE", AUDIENCE)
    get_settings.cache_clear()
    jwks.reset_cache()
    yield
    get_settings.cache_clear()
    jwks.reset_cache()


def _stub_client(
    handler: Any,
) -> Any:
    """Serve the provider in-process through the module's client seam.

    Patching `httpx.AsyncClient` globally would also capture clients that have nothing to
    do with the identity provider, which silently redirected an entire test file's
    requests into this handler once already.
    """
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def served_jwks(monkeypatch: pytest.MonkeyPatch, jwks_document: dict[str, Any]) -> list[str]:
    """Stand up the issuer's discovery and JWKS endpoints in-process.

    Returns the list of paths fetched, so a test can assert on how often we went to the
    provider — the caching and rate-limiting behaviour is only observable that way.
    """
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(request.url.path)
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/keys"})
        if request.url.path == "/keys":
            return httpx.Response(200, json=jwks_document)
        return httpx.Response(404)

    monkeypatch.setattr(jwks, "_http_client", _stub_client(handler))
    return fetched


def _b64(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint(
    key: ec.EllipticCurvePrivateKey,
    *,
    algorithm: str = "ES256",
    kid: str | None = KID,
    **overrides: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "iat": now,
        "exp": now + 300,
        "email": "alice@customer.example",
    }
    claims.update(overrides)
    for name, value in list(claims.items()):
        if value is None:
            del claims[name]
    headers = {"kid": kid} if kid is not None else None
    signing: Any = key if algorithm.startswith("ES") else "shared-secret"
    return jwt.encode(claims, signing, algorithm=algorithm, headers=headers)


# ----------------------------------------------------------------------
# The happy path, so the negatives below mean something
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_valid_token_is_accepted(
    signing_key: ec.EllipticCurvePrivateKey, served_jwks: list[str]
) -> None:
    result, claims = await tokens.verify(mint(signing_key))

    assert result.subject == "user-1"
    assert result.email == "alice@customer.example"
    assert result.actor_ref == "person:alice@customer.example"
    assert claims["iss"] == ISSUER
    assert served_jwks == ["/.well-known/openid-configuration", "/keys"]


# ----------------------------------------------------------------------
# Forgery
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unsigned_token_is_rejected(
    signing_key: ec.EllipticCurvePrivateKey, served_jwks: list[str]
) -> None:
    """`alg: none` is the original JWT forgery: a token with no signature at all, which a
    verifier that trusts the header's algorithm will happily accept."""
    unsigned = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "attacker", "exp": int(time.time()) + 300},
        key="",
        algorithm="none",
        headers={"kid": KID},
    )

    with pytest.raises(tokens.TokenError):
        await tokens.verify(unsigned)


@pytest.mark.asyncio
async def test_a_token_signed_with_the_public_key_as_an_hmac_secret_is_rejected(
    signing_key: ec.EllipticCurvePrivateKey,
    jwks_document: dict[str, Any],
    served_jwks: list[str],
) -> None:
    """Algorithm confusion. The verification key is public by design, so if an HMAC
    algorithm is accepted the attacker signs with the key we verify with."""
    public_pem = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # Assembled by hand because `jwt.encode` refuses to sign an HMAC with a PEM, and an
    # attacker is not using our library's guardrails.
    now = int(time.time())
    header = _b64({"alg": "HS256", "typ": "JWT", "kid": KID})
    payload = _b64(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "attacker", "iat": now, "exp": now + 300}
    )
    signing_input = f"{header}.{payload}".encode()
    mac = hmac.new(public_pem, signing_input, hashlib.sha256).digest()
    forged = f"{header}.{payload}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"

    with pytest.raises(tokens.TokenError):
        await tokens.verify(forged)


@pytest.mark.asyncio
async def test_a_token_signed_by_another_key_is_rejected(
    served_jwks: list[str],
) -> None:
    other = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(tokens.TokenError):
        await tokens.verify(mint(other))


# ----------------------------------------------------------------------
# Claim checks
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_expired_token_is_rejected(
    signing_key: ec.EllipticCurvePrivateKey, served_jwks: list[str]
) -> None:
    past = int(time.time()) - 3600
    with pytest.raises(tokens.TokenError):
        await tokens.verify(mint(signing_key, iat=past, exp=past + 60))


@pytest.mark.asyncio
async def test_a_token_for_another_audience_is_rejected(
    signing_key: ec.EllipticCurvePrivateKey, served_jwks: list[str]
) -> None:
    """Without this check, any token the customer's IdP issued to any other application
    is a valid credential here."""
    with pytest.raises(tokens.TokenError):
        await tokens.verify(mint(signing_key, aud="some-other-app"))


@pytest.mark.asyncio
async def test_a_token_from_another_issuer_is_rejected(
    signing_key: ec.EllipticCurvePrivateKey, served_jwks: list[str]
) -> None:
    with pytest.raises(tokens.TokenError):
        await tokens.verify(mint(signing_key, iss="https://attacker.example"))


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["sub", "exp", "iat", "aud", "iss"])
async def test_a_token_missing_a_required_claim_is_rejected(
    signing_key: ec.EllipticCurvePrivateKey, served_jwks: list[str], missing: str
) -> None:
    with pytest.raises(tokens.TokenError):
        await tokens.verify(mint(signing_key, **{missing: None}))


@pytest.mark.asyncio
async def test_a_malformed_token_is_rejected(served_jwks: list[str]) -> None:
    with pytest.raises(tokens.TokenError):
        await tokens.verify("not-a-jwt")


@pytest.mark.parametrize(
    "header",
    [None, "", "token abc", "Bearer", "Bearer   ", "Basic dXNlcjpwYXNz"],
)
def test_a_non_bearer_authorization_header_is_refused(header: str | None) -> None:
    with pytest.raises(tokens.TokenError):
        tokens.bearer_from_header(header)


def test_the_bearer_scheme_is_matched_case_insensitively() -> None:
    assert tokens.bearer_from_header("bearer abc") == "abc"
    assert tokens.bearer_from_header("BEARER abc") == "abc"


# ----------------------------------------------------------------------
# Key handling
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keys_are_cached_across_requests(
    signing_key: ec.EllipticCurvePrivateKey, served_jwks: list[str]
) -> None:
    await tokens.verify(mint(signing_key))
    await tokens.verify(mint(signing_key))

    assert served_jwks.count("/keys") == 1, "second verification refetched the JWKS"


@pytest.mark.asyncio
async def test_invented_key_ids_do_not_become_traffic_at_the_provider(
    signing_key: ec.EllipticCurvePrivateKey, served_jwks: list[str]
) -> None:
    """`kid` is attacker-controlled and unauthenticated, so a refetch per unknown value
    would let anyone use us to hammer the customer's identity provider."""
    await tokens.verify(mint(signing_key))
    assert served_jwks.count("/keys") == 1

    for n in range(20):
        with pytest.raises(tokens.TokenError):
            await tokens.verify(mint(signing_key, kid=f"invented-{n}"))

    assert served_jwks.count("/keys") == 1, "unknown kid became an amplifier"


@pytest.mark.asyncio
async def test_a_rotated_key_is_picked_up_without_waiting_for_the_ttl(
    monkeypatch: pytest.MonkeyPatch,
    jwks_document: dict[str, Any],
    served_jwks: list[str],
) -> None:
    """The cache TTL is an hour. A rotation must cost the refresh interval, not that."""
    clock = [1000.0]
    monkeypatch.setattr(jwks.time, "monotonic", lambda: clock[0])

    old_key = ec.generate_private_key(ec.SECP256R1())
    old_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(old_key.public_key()))
    old_jwk.update({"kid": "old-key", "use": "sig", "alg": "ES256"})
    jwks_document["keys"] = [old_jwk]

    await tokens.verify(mint(old_key, kid="old-key"))
    assert served_jwks.count("/keys") == 1

    # The provider rotates. Our cache still holds only the retired key.
    new_key = ec.generate_private_key(ec.SECP256R1())
    new_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(new_key.public_key()))
    new_jwk.update({"kid": "new-key", "use": "sig", "alg": "ES256"})
    jwks_document["keys"] = [new_jwk]

    # Immediately after: refused, because it is not yet our turn to ask.
    with pytest.raises(tokens.TokenError):
        await tokens.verify(mint(new_key, kid="new-key"))
    assert served_jwks.count("/keys") == 1

    clock[0] += 11.0  # past _MIN_REFRESH_INTERVAL, far short of the TTL

    result, _ = await tokens.verify(mint(new_key, kid="new-key"))
    assert result.subject == "user-1"
    assert served_jwks.count("/keys") == 2


@pytest.mark.asyncio
async def test_cached_keys_outlive_the_ttl_when_the_provider_is_down(
    monkeypatch: pytest.MonkeyPatch,
    signing_key: ec.EllipticCurvePrivateKey,
    jwks_document: dict[str, Any],
) -> None:
    """Rejecting valid sessions because the identity provider is briefly unreachable is
    a larger outage than the one it avoids."""
    clock = [1000.0]
    monkeypatch.setattr(jwks.time, "monotonic", lambda: clock[0])

    reachable = [True]

    def handler(request: httpx.Request) -> httpx.Response:
        if not reachable[0]:
            raise httpx.ConnectError("connection refused")
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/keys"})
        return httpx.Response(200, json=jwks_document)

    monkeypatch.setattr(jwks, "_http_client", _stub_client(handler))

    await tokens.verify(mint(signing_key))

    reachable[0] = False
    clock[0] += get_settings().oidc_jwks_cache_seconds + 60

    result, _ = await tokens.verify(mint(signing_key))
    assert result.subject == "user-1"


@pytest.mark.asyncio
async def test_a_discovery_document_for_a_different_issuer_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    signing_key: ec.EllipticCurvePrivateKey,
    jwks_document: dict[str, Any],
) -> None:
    """A redirect or a typo that moves discovery to another provider would otherwise
    move trust with it silently."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={"issuer": "https://elsewhere.example", "jwks_uri": f"{ISSUER}/keys"},
            )
        return httpx.Response(200, json=jwks_document)

    monkeypatch.setattr(jwks, "_http_client", _stub_client(handler))

    with pytest.raises(tokens.IdentityProviderUnreachableError):
        await tokens.verify(mint(signing_key))


@pytest.mark.asyncio
async def test_an_unreachable_provider_is_not_reported_as_bad_credentials(
    monkeypatch: pytest.MonkeyPatch, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    """The distinction drives the status code: 503 keeps clients' sessions, 401 throws
    every user back to a login screen because of our outage."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(jwks, "_http_client", _stub_client(handler))

    with pytest.raises(tokens.IdentityProviderUnreachableError):
        await tokens.verify(mint(signing_key))


# ----------------------------------------------------------------------
# Principal derivation
# ----------------------------------------------------------------------


def test_scopes_are_read_from_either_spelling() -> None:
    """`scope` is space-delimited per OAuth, Entra sends `scp`, and roles arrive as
    arrays. Mishandling the shape yields an empty set, which fails open on any later
    "does this caller have that role" question."""
    oauth = principal.Principal.from_claims(
        {"sub": "a", "iss": ISSUER, "scope": "read:agents write:agents"}
    )
    entra = principal.Principal.from_claims(
        {"sub": "a", "iss": ISSUER, "scp": "read:agents write:agents"}
    )

    assert oauth.scopes == entra.scopes == {"read:agents", "write:agents"}


def test_roles_are_read_from_an_array() -> None:
    result = principal.Principal.from_claims(
        {"sub": "a", "iss": ISSUER, "roles": ["approver", "auditor"]}
    )
    assert result.roles == {"approver", "auditor"}


def test_a_principal_without_an_email_still_has_an_audit_reference() -> None:
    """Audit columns are never allowed to be empty, so `actor_ref` has to work from
    `sub` alone — and must not look like a verified email when it does."""
    result = principal.Principal.from_claims({"sub": "opaque-123", "iss": ISSUER})

    assert result.email is None
    assert result.actor_ref == f"subject:{ISSUER}#opaque-123"
    assert not result.actor_ref.startswith("person:")
