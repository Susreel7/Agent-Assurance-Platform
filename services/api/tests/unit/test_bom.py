"""BOM extraction tests against a realistic descriptor shape."""

from __future__ import annotations

from typing import Any

from app.domains.bom.service import extract_components


def _descriptor() -> dict[str, Any]:
    return {
        "aap_version": "0.1",
        "agent": {"urn": "urn:aap:acme:ops:helper", "version": "2.0.0"},
        "accountability": {
            "owning_team": "Ops",
            "accountable_person": "person:a@acme.com",
        },
        "runtime": {"framework": "langgraph"},
        "models": [
            {
                "provider": "anthropic",
                "family": "claude",
                "id": "claude-sonnet-4",
                "role": "primary",
            }
        ],
        "prompts": [{"name": "system", "digest": "sha256:" + "a" * 64}],
        "tools": [
            {"name": "search_claims", "effect": "read", "reversible": True},
        ],
        "references": {
            "mcp_servers": [{"url": "https://mcp.acme.com/tools", "digest": "sha256:" + "b" * 64}]
        },
        "data": {
            "sources": [
                {"name": "claims_db", "kind": "postgres", "region": "eu-west-1"},
                {"name": "embeddings", "kind": "vector_store", "region": "eu-west-1"},
            ]
        },
        "delegates_to": [{"urn": "urn:aap:acme:ops:specialist", "trust": "internal"}],
        "security": {"prompt_injection_defences": ["input_classifier", "tool_allowlist"]},
    }


def test_extract_components_covers_all_kinds() -> None:
    rows = extract_components(_descriptor())
    kinds = {row["kind"] for row in rows}
    assert kinds == {
        "model",
        "prompt",
        "tool",
        "mcp_server",
        "data_source",
        "vector_store",
        "sub_agent",
        "guardrail",
    }

    models = [r for r in rows if r["kind"] == "model"]
    assert models[0]["name"] == "anthropic/claude/claude-sonnet-4"
    assert models[0]["version"] == "primary"

    tools = [r for r in rows if r["kind"] == "tool"]
    assert tools[0]["effect"] == "read"
    assert tools[0]["reversible"] is True
