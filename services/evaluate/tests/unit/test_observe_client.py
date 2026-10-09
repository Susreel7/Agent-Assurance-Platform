from __future__ import annotations

import httpx
import pytest

from evaluate.clients.observe import ObserveClient
from evaluate.config import Settings

pytestmark = pytest.mark.asyncio


async def test_get_trace_summary_maps_spans() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/traces/t1")
        assert request.url.params["organization_id"]
        return httpx.Response(
            200,
            json={
                "trace_id": "t1",
                "spans": [
                    {
                        "span_id": "root",
                        "parent_span_id": None,
                        "duration_ms": 10,
                        "outcome": "success",
                    },
                    {"span_id": "child", "parent_span_id": "root", "duration_ms": 5},
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = ObserveClient(Settings(observe_base_url="http://observe.test"), transport=transport)
    summary = await client.get_trace_summary(
        org_id="org",
        project_id="proj",
        trace_id="t1",
        authorization="Bearer x",
    )
    assert summary["root_span_id"] == "root"
    assert summary["latency_ms"] == 15


async def test_poll_events_parses_live_tail_sse() -> None:
    sse = 'data: {"trace_id":"t9","type":"span","span_id":"s1","cursor":"42"}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/live-tail")
        return httpx.Response(200, content=sse.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    settings = Settings(
        observe_base_url="http://observe.test",
        observe_poll_max_events=5,
        observe_poll_live_tail_seconds=5.0,
    )
    client = ObserveClient(settings, transport=transport)
    out = await client.poll_events(
        org_id="org",
        project_id="proj",
        cursor="0",
        authorization="Bearer x",
    )
    assert out["next_cursor"] == "42"
    assert len(out["events"]) == 1
    assert out["events"][0]["trace_id"] == "t9"
    assert out["events"][0]["metadata"]["event_type"] == "span"
