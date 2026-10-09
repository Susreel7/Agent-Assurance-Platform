"""Verification keys, fetched from an issuer and cached.

An OIDC provider publishes its public keys at a JWKS endpoint and rotates them on its own
schedule, so the keys cannot be baked into configuration. This module owns fetching them
and nothing else: no token parsing, no claim interpretation.

The cache is keyed by JWKS URI rather than global, because `auth_providers` makes the set
of issuers a property of the data. One deployment now verifies tokens from the install's
own configured issuer *and* from each account's provider row, and a single-slot cache
would evict one on every request from the other.

Three failure modes shape the design.

**A rotation must not cause an outage.** Keys are cached for
``oidc_jwks_cache_seconds``, but an unknown key id triggers a refetch rather than waiting
for the TTL: a provider that has just rotated presents a `kid` we have never seen, and
every request would otherwise fail for up to an hour.

**That refetch must not become an amplifier.** An unauthenticated caller controls the
`kid` in a token header, so "unknown kid triggers a fetch" is a request we make to the
identity provider on anyone's behalf. One fetch per ``_MIN_REFRESH_INTERVAL`` per issuer
is therefore the ceiling, which bounds a rotation's disruption to that interval rather
than to the TTL.

**Keys outlive their TTL when the provider is unreachable.** The TTL exists to notice
rotations, not because an old key stops being able to verify the tokens it signed. So an
expired cache that can answer is used in preference to failing, and the provider's
availability does not become ours.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx
import jwt

from app.config import get_settings

log = logging.getLogger(__name__)

_MIN_REFRESH_INTERVAL = 10.0
"""Seconds. Floor between forced refetches, whatever the traffic asks for."""

_HTTP_TIMEOUT = httpx.Timeout(5.0, connect=3.0)

_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"


class JwksUnavailableError(RuntimeError):
    """The provider's keys could not be fetched. Distinct from an invalid token."""


class UnknownKeyError(LookupError):
    """The token names a key the provider does not publish."""


@dataclass
class _Cache:
    keys: jwt.PyJWKSet | None = None
    fetched_at: float = 0.0
    last_attempt_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# JWKS URI -> its keys. Issuer -> its discovered JWKS URI.
_caches: dict[str, _Cache] = {}
_discovered: dict[str, str] = {}


def _cache_for(jwks_uri: str) -> _Cache:
    cache = _caches.get(jwks_uri)
    if cache is None:
        cache = _Cache()
        _caches[jwks_uri] = cache
    return cache


def _http_client() -> httpx.AsyncClient:
    """The client used to reach the identity provider.

    A named seam so tests can serve the provider in-process. Patching `httpx.AsyncClient`
    itself would be global and would capture every other client in the process, including
    the one a test uses to call our own app.

    Redirects are not followed: discovery and JWKS are fixed endpoints, and following a
    redirect would move key retrieval to a host the configuration never named.
    """
    return httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False)


async def discover_jwks_uri(issuer: str, override: str | None = None) -> str:
    """The JWKS endpoint for ``issuer``, from its discovery document.

    ``override`` short-circuits discovery, for an issuer that publishes no document or
    whose keys are mirrored internally — normal in an air-gapped install.
    """
    if override:
        return override
    normalised = issuer.rstrip("/")
    cached = _discovered.get(normalised)
    if cached is not None:
        return cached

    url = f"{normalised}{_DISCOVERY_SUFFIX}"
    async with _http_client() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JwksUnavailableError(f"OIDC discovery failed at {url}: {exc}") from exc

    # The issuer in the document must match the one configured. Otherwise a redirect, or
    # a misconfigured value, silently moves trust to a different provider — and every
    # token would then be validated against keys we never intended to trust.
    advertised = document.get("issuer")
    if advertised is not None and str(advertised).rstrip("/") != normalised:
        raise JwksUnavailableError(
            f"discovery document at {url} advertises issuer {advertised!r}, "
            f"which is not the configured {normalised!r}"
        )

    jwks_uri = document.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not jwks_uri:
        raise JwksUnavailableError(f"discovery document at {url} has no jwks_uri")

    _discovered[normalised] = jwks_uri
    return jwks_uri


async def _fetch(jwks_uri: str, cache: _Cache) -> jwt.PyJWKSet:
    async with _http_client() as client:
        try:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JwksUnavailableError(f"JWKS fetch failed at {jwks_uri}: {exc}") from exc

    try:
        # PyJWKSet skips keys it cannot use rather than rejecting the whole set, which is
        # what we want: a provider publishing an encryption key alongside its signing
        # keys is normal and must not break verification.
        keys = jwt.PyJWKSet.from_dict(payload)
    except jwt.PyJWKSetError as exc:
        raise JwksUnavailableError(f"JWKS at {jwks_uri} contains no usable keys: {exc}") from exc

    cache.keys = keys
    cache.fetched_at = time.monotonic()
    log.info("Fetched %d verification key(s) from %s", len(keys.keys), jwks_uri)
    return keys


def _lookup(keys: jwt.PyJWKSet, kid: str | None) -> jwt.PyJWK | None:
    for key in keys.keys:
        # A single-key JWKS is allowed to omit `kid` entirely, so an absent kid on both
        # sides is a match rather than an error.
        if key.key_id == kid or (kid is None and len(keys.keys) == 1):
            return key
    return None


async def key_for_jwks(jwks_uri: str, kid: str | None) -> jwt.PyJWK:
    """Return the verification key for a token's `kid` from one JWKS endpoint."""
    ttl = get_settings().oidc_jwks_cache_seconds
    cache = _cache_for(jwks_uri)

    async with cache.lock:
        now = time.monotonic()
        cached = cache.keys
        fresh = cached is not None and now - cache.fetched_at < ttl

        if cached is not None and fresh and _lookup(cached, kid) is not None:
            found = _lookup(cached, kid)
            assert found is not None
            return found

        # Past here a fetch is wanted: the cache is empty, past its TTL, or does not
        # contain this kid. The interval is the one rule governing all three, so at most
        # one request reaches the provider per interval however much traffic arrives.
        # It matters because `kid` is attacker-controlled and unauthenticated, which
        # makes "unknown kid refetches" a request we make on anyone's behalf.
        if cached is not None and now - cache.last_attempt_at < _MIN_REFRESH_INTERVAL:
            stale = _lookup(cached, kid)
            if stale is not None:
                # Known kid, just past the TTL, and it is not our turn to refetch.
                # Verification keys do not change meaning as they age; the TTL exists to
                # pick up rotations, not because an old key becomes unsafe.
                return stale
            raise UnknownKeyError(f"unknown key id {kid!r}")

        cache.last_attempt_at = now
        try:
            keys = await _fetch(jwks_uri, cache)
        except JwksUnavailableError:
            # A provider outage must not become ours. Keys we already hold still verify
            # tokens the provider signed with them, so serving them beyond the TTL is
            # strictly better than rejecting valid sessions.
            if cached is not None:
                stale = _lookup(cached, kid)
                if stale is not None:
                    log.warning("Serving stale verification keys: provider unreachable")
                    return stale
            raise

    found = _lookup(keys, kid)
    if found is None:
        raise UnknownKeyError(f"unknown key id {kid!r}")
    return found


async def key_for_issuer(issuer: str, jwks_uri: str | None, kid: str | None) -> jwt.PyJWK:
    """Discover an issuer's keys and return the one naming ``kid``.

    The provider path. ``key_for`` below is the same thing for the install's own
    configured issuer, which is the credential the gateway and the SDKs present.
    """
    return await key_for_jwks(await discover_jwks_uri(issuer, jwks_uri), kid)


async def key_for(kid: str | None) -> jwt.PyJWK:
    """Return the verification key for the install's configured issuer."""
    settings = get_settings()
    if settings.oidc_issuer is None and settings.oidc_jwks_url is None:
        raise JwksUnavailableError("no OIDC issuer configured")
    if settings.oidc_jwks_url:
        return await key_for_jwks(settings.oidc_jwks_url, kid)
    assert settings.oidc_issuer is not None
    return await key_for_issuer(settings.oidc_issuer, None, kid)


def reset_cache() -> None:
    """Drop cached keys and discovery results. For tests, and for a deliberate reload."""
    _caches.clear()
    _discovered.clear()
