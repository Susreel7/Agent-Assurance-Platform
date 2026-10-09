"""Composition parsing and reconciliation logic."""

from __future__ import annotations

from typing import Any

import pytest

from app.domains.composition.schemas import CompositionElementKind, ReconciliationStatus
from app.domains.composition.service import (
    CompositionError,
    build_element_view,
    model_allowed,
    parse_composition_block,
)
from app.domains.operations.service import declaration_keys


def _descriptor(**composition: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "aap_version": "0.1",
        "agent": {"urn": "urn:aap:acme:ops:helper", "version": "1.0.0"},
        "tools": [{"name": "alpha_tool"}, {"name": "beta_tool"}],
        "references": {
            "mcp_servers": [
                {"name": "stripe", "url": "https://mcp.example.com/stripe"},
            ]
        },
        "models": [{"provider": "anthropic", "id": "claude-sonnet-4"}],
        "composition": composition,
    }
    return base


def test_element_identity_survives_reordering() -> None:
    first = _descriptor(
        skills=[
            {"name": "b_skill", "path": "a", "digest": "sha256:" + "a" * 64},
            {"name": "a_skill", "path": "b", "digest": "sha256:" + "b" * 64},
        ]
    )
    second = _descriptor(
        skills=[
            {"name": "a_skill", "path": "b", "digest": "sha256:" + "b" * 64},
            {"name": "b_skill", "path": "a", "digest": "sha256:" + "a" * 64},
        ]
    )
    observed: dict[tuple[CompositionElementKind, str], int] = {}
    skill = CompositionElementKind.SKILL
    keys_first = {e.key for e in build_element_view(first, observed) if e.kind == skill}
    keys_second = {e.key for e in build_element_view(second, observed) if e.kind == skill}
    assert keys_first == keys_second == {"a_skill", "b_skill"}


def test_rule_obligation_schema_rejects_long_statement() -> None:
    with pytest.raises(CompositionError):
        parse_composition_block(
            _descriptor(
                rule_obligations=[
                    {
                        "id": "OBL-1",
                        "source_ref": "agents_md",
                        "category": "pii",
                        "polarity": "forbid",
                        "statement": "x" * 600,
                        "strength": "binding",
                        "digest": "sha256:" + "c" * 64,
                    }
                ]
            )
        )


def test_mcp_declaration_keys_normalises_url_to_short_name() -> None:
    url = "https://mcp.northwind.internal/stripe"
    assert "stripe" in declaration_keys(url)


def test_model_policy_conflict_when_observed_outside_allowlist() -> None:
    desc = _descriptor(
        model_policy={
            "selection_mode": "pinned",
            "pin": {"provider": "anthropic", "id": "claude-sonnet-4"},
        }
    )
    observed = {(CompositionElementKind.MODEL, "gpt-4o"): 3}
    elements = build_element_view(desc, observed)
    rogue = next(e for e in elements if e.key == "gpt-4o")
    assert rogue.status == ReconciliationStatus.CONFLICT
    assert model_allowed("gpt-4o", {"claude-sonnet-4"}) is False


def test_observed_only_tool() -> None:
    desc = _descriptor()
    observed = {(CompositionElementKind.TOOL, "secret_tool"): 2}
    row = next(e for e in build_element_view(desc, observed) if e.key == "secret_tool")
    assert row.status == ReconciliationStatus.OBSERVED_ONLY
    assert row.declared is False
    assert row.observed is True
