from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_live_router_models_optional() -> None:
    base = os.environ.get("PROMPT_ROUTER_INTEGRATION_URL")
    if not base:
        pytest.skip("set PROMPT_ROUTER_INTEGRATION_URL for live router contract test")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{base.rstrip('/')}/v1/models")
    assert resp.status_code in {200, 401, 403}
