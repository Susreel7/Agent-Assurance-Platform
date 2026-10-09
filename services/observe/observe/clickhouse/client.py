"""ClickHouse HTTP client — parameterized queries only for user input."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import httpx

from observe.config import Settings
from observe.query.filters import SpanSearchFilters

log = logging.getLogger(__name__)


class ClickHouseClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.clickhouse_url.rstrip("/")
        self._database = settings.clickhouse_database
        self._auth = (settings.clickhouse_user, settings.clickhouse_password)

    def ping(self) -> None:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{self._base}/ping", auth=self._auth or None)
            resp.raise_for_status()

    def execute(self, sql: str, *, parameters: dict[str, Any] | None = None) -> str:
        params: dict[str, str] = {"database": self._database}
        if parameters:
            for key, value in parameters.items():
                params[f"param_{key}"] = str(value)
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{self._base}/",
                params=params,
                content=sql.encode("utf-8"),
                auth=self._auth or None,
            )
            if resp.is_error:
                raise RuntimeError(
                    f"ClickHouse request failed ({resp.status_code}): {resp.text[:2048]}"
                )
            return resp.text

    def query_json(
        self, sql: str, *, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        with httpx.Client(timeout=120.0) as client:
            params: dict[str, str] = {"database": self._database}
            if parameters:
                for key, value in parameters.items():
                    params[f"param_{key}"] = str(value)
            resp = client.post(
                f"{self._base}/",
                params=params,
                content=(sql + " FORMAT JSON").encode("utf-8"),
                auth=self._auth or None,
            )
            if resp.is_error:
                raise RuntimeError(
                    f"ClickHouse query failed ({resp.status_code}): {resp.text[:2048]}"
                )
            data = resp.json()
        return list(data.get("data", []))

    def insert_spans_json_each_row(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        payload = "\n".join(json.dumps(r, default=str) for r in rows)
        sql = f"INSERT INTO {self._database}.spans FORMAT JSONEachRow\n{payload}"
        self.execute(sql)

    def insert_trace_index_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        payload = "\n".join(json.dumps(r, default=str) for r in rows)
        sql = f"INSERT INTO {self._database}.trace_index FORMAT JSONEachRow\n{payload}"
        self.execute(sql)

    def insert_events_json_each_row(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        payload = "\n".join(json.dumps(r, default=str) for r in rows)
        sql = f"INSERT INTO {self._database}.events FORMAT JSONEachRow\n{payload}"
        self.execute(sql)

    def insert_execution_edges_json_each_row(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        payload = "\n".join(json.dumps(r, default=str) for r in rows)
        sql = f"INSERT INTO {self._database}.execution_edges FORMAT JSONEachRow\n{payload}"
        self.execute(sql)

    def insert_execution_index_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        payload = "\n".join(json.dumps(r, default=str) for r in rows)
        sql = f"INSERT INTO {self._database}.execution_index FORMAT JSONEachRow\n{payload}"
        self.execute(sql)

    def spans_for_trace_final(
        self,
        org_id: UUID,
        project_id: UUID,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        sql = f"""
        SELECT span_id, parent_span_id, parent_trace_id, execution_id, parent_execution_id, kind,
               observation_type, operation_name, outcome, model, tool_name, provider,
               sdk_name, sdk_version, sdk_operation, mcp_server, mcp_method, retry_attempt,
               mcp_role, mcp_request_id, a2a_target_agent_id, a2a_target_execution_id,
               a2a_target_trace_id,
               graph_node_id, graph_node_path, initiating_user_id, effective_actor_id,
               effective_actor_type, user_session_id, environment_id, agent_version_id,
               invocation_source, application_name, client_name, request_id,
               replay_of_execution_id, replay_reason, repository_ref, branch_ref, commit_sha,
               deployment_name, region_name, runtime_name, framework, framework_version,
               duration_ms, source_convention, start_time, end_time, is_terminal, session_id,
               service_name, agent_id, agent_name, search_text, tags,
               input_tokens, output_tokens, cost_micros, sample_rate
        FROM {self._database}.spans FINAL
        WHERE organization_id = {{org_id:UUID}}
          AND project_id = {{project_id:UUID}}
          AND trace_id = {{trace_id:String}}
        ORDER BY start_time
        """
        rows = self.query_json(
            sql,
            parameters={"org_id": str(org_id), "project_id": str(project_id), "trace_id": trace_id},
        )
        for row in rows:
            parent_span_id = str(row.get("parent_span_id") or "").strip("\x00")
            row["parent_span_id"] = parent_span_id or None
        return rows

    def count_spans_for_trace(self, org_id: UUID, project_id: UUID, trace_id: str) -> int:
        sql = f"""
        SELECT count() AS c FROM {self._database}.spans FINAL
        WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
          AND trace_id = {{trace_id:String}}
        """
        rows = self.query_json(
            sql,
            parameters={"org_id": str(org_id), "project_id": str(project_id), "trace_id": trace_id},
        )
        return int(rows[0]["c"]) if rows else 0

    def search_traces(
        self,
        org_id: UUID,
        project_id: UUID,
        filters: SpanSearchFilters,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = filters.to_clickhouse_span_where(org_id, project_id)
        sql = f"""
        SELECT trace_id,
               anyIf(session_id, session_id != '') AS grouped_session_id,
               anyIf(service_name, service_name != '') AS grouped_service_name,
               anyIf(agent_id, agent_id != '') AS grouped_agent_id,
               count() AS span_count,
               min(start_time) AS start_time,
               max(end_time) AS end_time,
               sum(cost_micros) AS total_cost_micros,
               if(countIf(outcome = 'error') > 0, 'error',
                  if(countIf(outcome = 'open') > 0, 'open', 'success')) AS outcome
        FROM {self._database}.spans FINAL
        WHERE {where}
        GROUP BY trace_id
        ORDER BY start_time DESC
        LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """
        params["limit"] = str(filters.limit)
        params["offset"] = str(filters.offset)
        rows = self.query_json(sql, parameters=params)
        for row in rows:
            row["session_id"] = row.pop("grouped_session_id", "")
            row["service_name"] = row.pop("grouped_service_name", "")
            row["agent_id"] = row.pop("grouped_agent_id", "")
        count_sql = f"""
        SELECT uniqExact(trace_id) AS c FROM {self._database}.spans FINAL WHERE {where}
        """
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        total = int(self.query_json(count_sql, parameters=count_params)[0]["c"])
        return rows, total

    def aggregate_metrics(
        self,
        org_id: UUID,
        project_id: UUID,
        filters: SpanSearchFilters,
    ) -> dict[str, Any]:
        where, params = filters.to_clickhouse_span_where(org_id, project_id)
        sql = f"""
        SELECT
            count() AS span_count,
            uniqExact(trace_id) AS trace_count,
            avg(duration_ms) AS avg_latency_ms,
            quantileTDigest(0.50)(duration_ms) AS p50_latency_ms,
            quantileTDigest(0.95)(duration_ms) AS p95_latency_ms,
            quantileTDigest(0.99)(duration_ms) AS p99_latency_ms,
            sum(input_tokens) AS input_tokens,
            sum(output_tokens) AS output_tokens,
            sum(cost_micros) AS total_cost_micros,
            countIf(outcome = 'error') / greatest(count(), 1) AS error_rate
        FROM {self._database}.spans FINAL
        WHERE {where}
        """
        rows = self.query_json(sql, parameters=params)
        return rows[0] if rows else {}

    def operation_breakdown(
        self,
        org_id: UUID,
        project_id: UUID,
        *,
        dimension: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        dimensions = {
            "model": ("model", "model != ''"),
            "tool": ("tool_name", "tool_name != ''"),
            "sdk": (
                "concat(sdk_name, if(sdk_operation = '', '', concat(' · ', sdk_operation)))",
                "sdk_name != ''",
            ),
            "mcp": (
                "concat(mcp_server, if(mcp_method = '', '', concat(' · ', mcp_method)))",
                "mcp_server != ''",
            ),
        }
        selected = dimensions.get(dimension)
        if selected is None:
            raise ValueError(f"unsupported operation dimension: {dimension}")
        expression, predicate = selected
        sql = f"""
        SELECT
            {expression} AS label,
            count() AS count,
            countIf(outcome = 'error') AS failed_count,
            avg(duration_ms) AS avg_duration_ms,
            sum(cost_micros) AS total_cost_micros
        FROM {self._database}.spans FINAL
        WHERE organization_id = {{org_id:UUID}}
          AND project_id = {{project_id:UUID}}
          AND {predicate}
        GROUP BY label
        ORDER BY count DESC, label
        LIMIT {{limit:UInt32}}
        """
        return self.query_json(
            sql,
            parameters={
                "org_id": str(org_id),
                "project_id": str(project_id),
                "limit": str(limit),
            },
        )

    def time_series(
        self,
        org_id: UUID,
        project_id: UUID,
        filters: SpanSearchFilters,
        *,
        bucket_seconds: int,
    ) -> list[dict[str, Any]]:
        where, params = filters.to_clickhouse_span_where(org_id, project_id)
        params["bucket"] = str(bucket_seconds)
        sql = f"""
        SELECT
            toStartOfInterval(start_time, INTERVAL {{bucket:UInt32}} second) AS bucket,
            count() AS span_count,
            avg(duration_ms) AS avg_latency_ms,
            sum(cost_micros) AS cost_micros
        FROM {self._database}.spans FINAL
        WHERE {where}
        GROUP BY bucket
        ORDER BY bucket
        """
        return self.query_json(sql, parameters=params)

    def search_facets(
        self,
        org_id: UUID,
        project_id: UUID,
        filters: SpanSearchFilters,
    ) -> dict[str, Any]:
        where, params = filters.to_clickhouse_span_where(org_id, project_id)
        kinds = self.query_json(
            f"""
            SELECT kind, count() AS c FROM {self._database}.spans FINAL
            WHERE {where} GROUP BY kind ORDER BY c DESC LIMIT 20
            """,
            parameters=params,
        )
        models = self.query_json(
            f"""
            SELECT model, count() AS c FROM {self._database}.spans FINAL
            WHERE {where} AND model != '' GROUP BY model ORDER BY c DESC LIMIT 20
            """,
            parameters=params,
        )
        agents = self.query_json(
            f"""
            SELECT agent_id, count() AS c FROM {self._database}.spans FINAL
            WHERE {where} AND agent_id != '' GROUP BY agent_id ORDER BY c DESC LIMIT 50
            """,
            parameters=params,
        )
        tools = self.query_json(
            f"""
            SELECT tool_name, count() AS c FROM {self._database}.spans FINAL
            WHERE {where} AND tool_name != '' GROUP BY tool_name ORDER BY c DESC LIMIT 50
            """,
            parameters=params,
        )
        time_range = self.query_json(
            f"""
            SELECT min(start_time) AS start, max(end_time) AS end
            FROM {self._database}.spans FINAL WHERE {where}
            """,
            parameters=params,
        )
        bounds = time_range[0] if time_range else {}
        return {
            "kinds": [str(r["kind"]) for r in kinds],
            "models": [str(r["model"]) for r in models],
            "agents": [str(r["agent_id"]) for r in agents],
            "tools": [str(r["tool_name"]) for r in tools],
            "time_range": {
                "start": str(bounds["start"]) if bounds.get("start") else None,
                "end": str(bounds["end"]) if bounds.get("end") else None,
            },
        }

    def list_sessions(
        self,
        org_id: UUID,
        project_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        sql = f"""
        SELECT session_id, count(DISTINCT trace_id) AS trace_count,
               min(start_time) AS first_seen_at, max(end_time) AS last_seen_at,
               sum(span_count) AS span_count,
               sum(total_cost_micros) AS total_cost_micros,
               countIf(outcome = 'error') AS error_count,
               groupUniqArrayIf(agent_id, agent_id != '') AS agent_ids
        FROM {self._database}.trace_index FINAL
        WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
          AND session_id != ''
        GROUP BY session_id
        ORDER BY last_seen DESC
        LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """
        return self.query_json(
            sql,
            parameters={
                "org_id": str(org_id),
                "project_id": str(project_id),
                "limit": limit,
                "offset": offset,
            },
        )

    def count_sessions(self, org_id: UUID, project_id: UUID) -> int:
        sql = f"""
        SELECT uniqExact(session_id) AS c
        FROM {self._database}.trace_index FINAL
        WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
          AND session_id != ''
        """
        rows = self.query_json(
            sql, parameters={"org_id": str(org_id), "project_id": str(project_id)}
        )
        return int(rows[0]["c"]) if rows else 0

    def events_for_trace(
        self, org_id: UUID, project_id: UUID, trace_id: str
    ) -> list[dict[str, Any]]:
        sql = f"""
        SELECT event_type, observation_type, event_time, status, span_id, execution_id,
               initiating_user_id, effective_actor_id, agent_id, model, tool_name,
               sdk_name, sdk_operation, mcp_server, mcp_method, sequence, attributes
        FROM {self._database}.events FINAL
        WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
          AND trace_id = {{trace_id:String}}
        ORDER BY event_time, sequence
        """
        return self.query_json(
            sql,
            parameters={"org_id": str(org_id), "project_id": str(project_id), "trace_id": trace_id},
        )

    def search_executions(
        self,
        org_id: UUID,
        project_id: UUID,
        *,
        limit: int,
        offset: int,
        initiating_user_id: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses = [
            "organization_id = {org_id:UUID}",
            "project_id = {project_id:UUID}",
        ]
        params: dict[str, Any] = {"org_id": str(org_id), "project_id": str(project_id)}
        if initiating_user_id:
            clauses.append("initiating_user_id = {user_id:String}")
            params["user_id"] = initiating_user_id
        if status:
            clauses.append("status = {status:String}")
            params["status"] = status
        where = " AND ".join(clauses)
        sql = f"""
        SELECT execution_id, execution_type, trace_id, status, agent_id, agent_version_id,
               initiating_user_id, start_time, end_time, duration_ms, span_count,
               generation_count, tool_count, sdk_count, error_count, total_cost_micros,
               is_live, is_partial
        FROM {self._database}.execution_index FINAL
        WHERE {where}
        ORDER BY start_time DESC
        LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """
        params["limit"] = limit
        params["offset"] = offset
        rows = self.query_json(sql, parameters=params)
        count_sql = f"SELECT count() AS c FROM {self._database}.execution_index FINAL WHERE {where}"
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        total = int(self.query_json(count_sql, parameters=count_params)[0]["c"])
        return rows, total

    def get_execution_index(
        self, org_id: UUID, project_id: UUID, execution_id: str
    ) -> dict[str, Any] | None:
        sql = f"""
        SELECT * FROM {self._database}.execution_index FINAL
        WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
          AND execution_id = {{execution_id:String}}
        LIMIT 1
        """
        rows = self.query_json(
            sql,
            parameters={
                "org_id": str(org_id),
                "project_id": str(project_id),
                "execution_id": execution_id,
            },
        )
        return rows[0] if rows else None

    def events_for_execution(
        self, org_id: UUID, project_id: UUID, execution_id: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        sql = f"""
        SELECT event_uid, execution_id, trace_id, span_id, event_type, observation_type,
               event_time, status, initiating_user_id, effective_actor_id, agent_id, model,
               tool_name, sdk_name, sdk_operation, mcp_server, mcp_method, sequence, attributes
        FROM {self._database}.events FINAL
        WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
          AND execution_id = {{execution_id:String}}
        ORDER BY event_time, sequence
        LIMIT {{limit:UInt32}}
        """
        return self.query_json(
            sql,
            parameters={
                "org_id": str(org_id),
                "project_id": str(project_id),
                "execution_id": execution_id,
                "limit": limit,
            },
        )
