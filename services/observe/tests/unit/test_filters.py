from __future__ import annotations

from uuid import uuid4

from observe.clickhouse.client import ClickHouseClient
from observe.config import Settings
from observe.query.filters import SpanSearchFilters


def test_clickhouse_where_uses_parameters_only() -> None:
    org = uuid4()
    proj = uuid4()
    filters = SpanSearchFilters(
        session_id="sess-1",
        initiating_user_id="entra-user-1",
        text="hello",
    )
    where, params = filters.to_clickhouse_span_where(org, proj)
    assert "sess-1" not in where
    assert params["session_id"] == "sess-1"
    assert params["initiating_user_id"] == "entra-user-1"
    assert params["text"] == "hello"
    assert "{org_id:UUID}" in where


def test_trace_search_avoids_filter_alias_collisions(monkeypatch) -> None:
    client = ClickHouseClient(Settings())
    queries: list[str] = []

    def fake_query(sql: str, *, parameters=None):
        queries.append(sql)
        if "uniqExact" in sql:
            return [{"c": 1}]
        return [
            {
                "trace_id": "trace-1",
                "grouped_session_id": "session-1",
                "grouped_service_name": "service-1",
                "grouped_agent_id": "agent-1",
            }
        ]

    monkeypatch.setattr(client, "query_json", fake_query)
    rows, total = client.search_traces(
        uuid4(),
        uuid4(),
        SpanSearchFilters(session_id="session-1", agent_id="agent-1"),
    )

    assert total == 1
    assert rows[0]["session_id"] == "session-1"
    assert rows[0]["service_name"] == "service-1"
    assert rows[0]["agent_id"] == "agent-1"
    assert "AS session_id" not in queries[0]
    assert "AS agent_id" not in queries[0]


def test_trace_reconstruction_queries_execution_context(monkeypatch) -> None:
    client = ClickHouseClient(Settings())
    queries: list[str] = []

    def fake_query(sql: str, *, parameters=None):
        queries.append(sql)
        return [{"span_id": "root", "parent_span_id": "\x00" * 16}]

    monkeypatch.setattr(client, "query_json", fake_query)
    rows = client.spans_for_trace_final(uuid4(), uuid4(), "trace-1")

    sql = queries[0]
    assert rows[0]["parent_span_id"] is None
    for column in (
        "parent_trace_id",
        "invocation_source",
        "application_name",
        "client_name",
        "request_id",
        "replay_of_execution_id",
        "framework",
        "framework_version",
    ):
        assert column in sql
