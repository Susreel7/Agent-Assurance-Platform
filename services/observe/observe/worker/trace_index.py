"""Build trace_index rows from normalized spans."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from observe.worker.normalizer import NormalizedSpan


def build_trace_index_rows(
    org_id: UUID,
    project_id: UUID,
    spans: list[NormalizedSpan],
    *,
    version: int,
    nano_to_ch: Any,
) -> list[dict[str, Any]]:
    by_trace: dict[str, list[NormalizedSpan]] = {}
    for s in spans:
        by_trace.setdefault(s.trace_id, []).append(s)
    rows: list[dict[str, Any]] = []
    for trace_id, group in by_trace.items():
        starts = [s.start_time_unix_nano for s in group if s.start_time_unix_nano > 0]
        ends = [s.end_time_unix_nano for s in group if s.end_time_unix_nano > 0]
        start = min(starts) if starts else 0
        end = max(ends) if ends else 0
        session = next((g.session_id for g in group if g.session_id), "")
        service = next((g.service_name for g in group if g.service_name), "")
        agent = next((g.agent_id for g in group if g.agent_id), "")
        cost = sum(g.cost_micros for g in group)
        outcome = next((g.outcome for g in group if g.outcome), "unknown")
        rows.append(
            {
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "trace_id": trace_id,
                "session_id": session or "",
                "service_name": service or "",
                "agent_id": agent or "",
                "root_span_id": "",
                "span_count": len(group),
                "start_time": nano_to_ch(start),
                "end_time": nano_to_ch(end),
                "total_cost_micros": cost,
                "outcome": outcome,
                "version": version,
            }
        )
    return rows
