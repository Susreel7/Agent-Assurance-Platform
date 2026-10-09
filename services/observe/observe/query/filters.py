"""Parameterized ClickHouse filter builders."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SpanSearchFilters(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    session_id: str | None = None
    agent_id: str | None = None
    initiating_user_id: str | None = None
    kind: str | None = None
    model: str | None = None
    tool_name: str | None = None
    outcome: str | None = None
    text: str | None = None
    start_after: datetime | None = None
    start_before: datetime | None = None
    min_latency_ms: float | None = None
    max_latency_ms: float | None = None
    min_cost_micros: int | None = None
    max_cost_micros: int | None = None

    def to_clickhouse_where(self, org_id: UUID, project_id: UUID) -> tuple[str, dict[str, str]]:
        clauses = [
            "organization_id = {org_id:UUID}",
            "project_id = {project_id:UUID}",
        ]
        params: dict[str, str] = {"org_id": str(org_id), "project_id": str(project_id)}
        if self.session_id:
            clauses.append("session_id = {session_id:String}")
            params["session_id"] = self.session_id
        if self.agent_id:
            clauses.append("agent_id = {agent_id:String}")
            params["agent_id"] = self.agent_id
        if self.initiating_user_id:
            clauses.append("initiating_user_id = {initiating_user_id:String}")
            params["initiating_user_id"] = self.initiating_user_id
        if self.outcome:
            clauses.append("outcome = {outcome:String}")
            params["outcome"] = self.outcome
        if self.start_after:
            clauses.append("start_time >= {start_after:DateTime64(3)}")
            params["start_after"] = self.start_after.strftime("%Y-%m-%d %H:%M:%S")
        if self.start_before:
            clauses.append("start_time <= {start_before:DateTime64(3)}")
            params["start_before"] = self.start_before.strftime("%Y-%m-%d %H:%M:%S")
        return " AND ".join(clauses), params

    def to_clickhouse_span_where(
        self, org_id: UUID, project_id: UUID
    ) -> tuple[str, dict[str, str]]:
        clauses = [
            "organization_id = {org_id:UUID}",
            "project_id = {project_id:UUID}",
        ]
        params: dict[str, str] = {"org_id": str(org_id), "project_id": str(project_id)}
        if self.session_id:
            clauses.append("session_id = {session_id:String}")
            params["session_id"] = self.session_id
        if self.agent_id:
            clauses.append("agent_id = {agent_id:String}")
            params["agent_id"] = self.agent_id
        if self.initiating_user_id:
            clauses.append("initiating_user_id = {initiating_user_id:String}")
            params["initiating_user_id"] = self.initiating_user_id
        if self.kind:
            clauses.append("kind = {kind:String}")
            params["kind"] = self.kind
        if self.model:
            clauses.append("model = {model:String}")
            params["model"] = self.model
        if self.tool_name:
            clauses.append("tool_name = {tool_name:String}")
            params["tool_name"] = self.tool_name
        if self.outcome:
            clauses.append("outcome = {outcome:String}")
            params["outcome"] = self.outcome
        if self.text:
            clauses.append("positionCaseInsensitive(search_text, {text:String}) > 0")
            params["text"] = self.text[:256]
        if self.start_after:
            clauses.append("start_time >= {start_after:DateTime64(3)}")
            params["start_after"] = self.start_after.strftime("%Y-%m-%d %H:%M:%S")
        if self.start_before:
            clauses.append("start_time <= {start_before:DateTime64(3)}")
            params["start_before"] = self.start_before.strftime("%Y-%m-%d %H:%M:%S")
        if self.min_latency_ms is not None:
            clauses.append("duration_ms >= {min_lat:Float64}")
            params["min_lat"] = str(self.min_latency_ms)
        if self.max_latency_ms is not None:
            clauses.append("duration_ms <= {max_lat:Float64}")
            params["max_lat"] = str(self.max_latency_ms)
        if self.min_cost_micros is not None:
            clauses.append("cost_micros >= {min_cost:Int64}")
            params["min_cost"] = str(self.min_cost_micros)
        if self.max_cost_micros is not None:
            clauses.append("cost_micros <= {max_cost:Int64}")
            params["max_cost"] = str(self.max_cost_micros)
        return " AND ".join(clauses), params
