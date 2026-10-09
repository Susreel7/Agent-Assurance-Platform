"""Unit tests for graph derivation and reconciliation classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.domains.graph.schemas import GraphEdgeKind
from app.domains.graph.service import derive_declared_graph, summarise_reconciliation

AGENT_ID = UUID("11111111-1111-1111-1111-111111111111")
URN = "urn:aap:acme:insurance:claims-processor"


def _descriptor() -> dict[str, object]:
    return {
        "models": [
            {"provider": "anthropic", "family": "claude", "id": "sonnet", "role": "primary"}
        ],
        "prompts": [{"name": "system"}],
        "tools": [{"name": "claims_database", "kind": "mcp"}],
        "references": {"mcp_servers": [{"url": "https://mcp.example/claims"}]},
        "data": {
            "classes": ["customer_pii"],
            "sources": [{"name": "claims_db", "region": "eu-west-1"}],
            "residency": {"permitted_regions": ["eu-west-1"]},
        },
        "delegates_to": [{"urn": "urn:aap:acme:insurance:delegate"}],
        "accountability": {
            "owning_team": "Automation",
            "accountable_person": "person:owner@acme.com",
        },
        "security": {"prompt_injection_defences": ["tool_allowlist"]},
    }


def test_declared_graph_includes_models_tools_and_data_classes() -> None:
    nodes, edges = derive_declared_graph(AGENT_ID, URN, "Claims", _descriptor())
    kinds = {n.kind for n in nodes}
    assert "model" in kinds
    assert "tool" in kinds
    assert "data_class" in kinds
    assert "mcp_server" in kinds
    edge_kinds = {e.kind for e in edges}
    assert GraphEdgeKind.USES_MODEL.value in edge_kinds
    assert GraphEdgeKind.CONNECTS_MCP.value in edge_kinds
    assert GraphEdgeKind.DELEGATES_TO.value in edge_kinds


@dataclass
class ReconRow:
    src_id: UUID
    dst_id: UUID
    kind: str
    declared: bool
    observed: bool
    reconciliation: str
    last_seen_at: datetime
    observation_count: int


def test_reconciliation_summary_counts_gaps() -> None:
    now = datetime.now(UTC)
    rows = [
        ReconRow(UUID(int=1), UUID(int=2), "uses_model", True, True, "confirmed", now, 10),
        ReconRow(
            UUID(int=3), UUID(int=4), "invokes_tool", True, False, "declared_not_observed", now, 0
        ),
        ReconRow(
            UUID(int=5), UUID(int=6), "reads_data", False, True, "observed_not_declared", now, 3
        ),
    ]
    summary = summarise_reconciliation(rows)
    assert summary.confirmed == 1
    assert summary.declared_not_observed == 1
    assert summary.observed_not_declared == 1
    assert len(summary.rows) == 3
