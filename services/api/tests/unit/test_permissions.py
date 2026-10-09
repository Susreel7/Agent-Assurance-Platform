from __future__ import annotations

import pytest

from app.api.deps import Authenticated, require_permission
from app.api.errors import ApiError, Reason
from app.auth import Principal
from app.config import get_settings


def _auth(claims: dict[str, object]) -> Authenticated:
    return Authenticated(
        principal=Principal(subject="user-1", issuer="https://idp.example", email=None),
        claims=claims,
    )


@pytest.mark.asyncio
async def test_sensitive_observe_permission_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    get_settings.cache_clear()
    dependency = require_permission("observe:content:read")

    # `ApiError`, not `HTTPException`. The refusal now carries a reason code, which is
    # what lets the console say "you do not have permission to see this" rather than
    # "Something went wrong". A 403 with no reason was indistinguishable from a bug.
    with pytest.raises(ApiError) as denied:
        await dependency(_auth({"roles": ["viewer"]}))
    assert denied.value.status_code == 403
    assert denied.value.reason is Reason.MODULE_FORBIDDEN

    await dependency(_auth({"permissions": ["observe:content:read"]}))
    await dependency(_auth({"realm_access": {"roles": ["observe_admin"]}}))
    get_settings.cache_clear()
