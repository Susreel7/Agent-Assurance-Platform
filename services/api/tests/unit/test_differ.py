"""Semantic differ tests.

These are the highest-value tests in the repository for the release feature. The differ
is what makes a change legible, so every category it can report needs a test that pins
the expected category, severity and summary shape.

Deliberately includes the two cases that are easy to get wrong:

  * a reordered model list must produce no changes (position is not identity)
  * a model point-version bump must not look like a model replacement
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domains.releases.differ import diff_descriptors
from app.domains.releases.schemas import (
    ChangeCategory,
    ChangeOperation,
    ImpactDimension,
    Severity,
)


def descriptor(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "aap_version": "0.1",
        "agent": {
            "urn": "urn:aap:acme:insurance:claims-processor",
            "version": "3.4.0",
            "lifecycle_state": "production",
        },
        "accountability": {
            "owning_team": "Insurance Automation",
            "accountable_person": "person:j.doe@acme.com",
        },
        "runtime": {
            "framework": "langgraph",
            "framework_version": "0.2.74",
            "autonomy": "supervised",
        },
        "inference": {"temperature": 0.2, "max_tokens": 4096},
        "resilience": {"request_timeout_ms": 30000, "max_retries": 3},
        "models": [
            {
                "provider": "anthropic",
                "family": "claude",
                "id": "claude-sonnet-4-5",
                "hosting": "vendor_api",
                "endpoint_region": "eu-west-1",
                "role": "primary",
            }
        ],
        "prompts": [{"name": "system", "digest": "sha256:aaa"}],
        "data": {
            "classes": ["customer_pii"],
            "residency": {"permitted_regions": ["eu-west-1"], "cross_border": "prohibited"},
            "retention_days": 30,
            "sources": [{"name": "claims_db", "kind": "postgres", "region": "eu-west-1"}],
        },
        "capabilities": [
            {"name": "read_claim", "effect": "read", "reversible": True, "human_approval": "none"},
            {
                "name": "approve_claim",
                "effect": "write",
                "reversible": False,
                "human_approval": "required",
                "value_limit": {"currency": "EUR", "max": 5000},
            },
        ],
        "tools": [
            {"name": "claims_database", "kind": "mcp", "effect": "write", "reversible": True}
        ],
        "references": {"mcp_servers": [{"url": "https://mcp.acme/claims", "digest": "sha256:m1"}]},
        "security": {
            "authentication": "oauth2_client_credentials",
            "prompt_injection_defences": ["input_classifier", "tool_allowlist"],
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def find(changes: list[Any], path_fragment: str) -> Any:
    matches = [c for c in changes if path_fragment in c.path]
    assert matches, f"no change matched {path_fragment!r}; got {[c.path for c in changes]}"
    return matches[0]


# ----------------------------------------------------------------- no-op cases


def test_first_version_has_no_changes() -> None:
    diff = diff_descriptors(None, descriptor())
    assert diff.changes == []
    assert diff.from_semver is None
    assert diff.headline() == "No governed changes"


def test_identical_descriptors_produce_nothing() -> None:
    assert diff_descriptors(descriptor(), descriptor()).changes == []


def test_reordered_model_list_is_not_a_change() -> None:
    """Position is not identity. Getting this wrong would suspend accreditations for a
    cosmetic list reorder, which would destroy trust in the whole mechanism."""
    before = descriptor(
        models=[
            {"provider": "anthropic", "family": "claude", "id": "c1", "role": "primary"},
            {"provider": "openai", "family": "gpt", "id": "g1", "role": "fallback"},
        ]
    )
    after = descriptor(
        models=[
            {"provider": "openai", "family": "gpt", "id": "g1", "role": "fallback"},
            {"provider": "anthropic", "family": "claude", "id": "c1", "role": "primary"},
        ]
    )
    assert diff_descriptors(before, after).changes == []


# ----------------------------------------------------------------- model changes


def test_model_provider_change_is_critical() -> None:
    after = descriptor()
    after["models"][0]["provider"] = "openai"
    after["agent"]["version"] = "3.4.1"

    change = find(diff_descriptors(descriptor(), after).changes, "provider")

    assert change.category is ChangeCategory.MODEL
    assert change.operation is ChangeOperation.MODIFIED
    assert change.severity is Severity.CRITICAL
    assert ImpactDimension.COMPLIANCE in change.impacts
    assert "anthropic" in change.summary and "openai" in change.summary
    assert change.detail is not None


def test_model_point_version_bump_is_reported_separately_from_family() -> None:
    """A point release must be its own change at medium severity, not a replacement."""
    after = descriptor()
    after["models"][0]["id"] = "claude-sonnet-4-6"

    changes = diff_descriptors(descriptor(), after).changes

    assert len(changes) == 1
    assert changes[0].severity is Severity.MEDIUM
    assert "version" in changes[0].subject.lower()


def test_model_hosting_change_flags_compliance() -> None:
    after = descriptor()
    after["models"][0]["hosting"] = "self_hosted"

    change = find(diff_descriptors(descriptor(), after).changes, "hosting")
    assert change.severity is Severity.CRITICAL
    assert ImpactDimension.COMPLIANCE in change.impacts


def test_fallback_model_added() -> None:
    after = descriptor()
    after["models"].append(
        {"provider": "openai", "family": "gpt", "id": "gpt-4.1", "role": "fallback"}
    )

    change = find(diff_descriptors(descriptor(), after).changes, "role=fallback")
    assert change.operation is ChangeOperation.ADDED
    assert "fallback" in change.subject.lower()


# --------------------------------------------------- the user-visible config cases


def test_timeout_change_is_reported_with_consequence() -> None:
    """Invisible in a code diff if it lives in a config file, decisive at runtime."""
    after = descriptor(resilience={"request_timeout_ms": 5000})

    change = find(diff_descriptors(descriptor(), after).changes, "request_timeout_ms")

    assert change.category is ChangeCategory.RESILIENCE
    assert ImpactDimension.LATENCY in change.impacts
    assert "30000" in change.summary and "5000" in change.summary
    assert change.detail is not None and "load" in change.detail


def test_retry_change_flags_cost_and_latency() -> None:
    after = descriptor(resilience={"max_retries": 10})
    change = find(diff_descriptors(descriptor(), after).changes, "max_retries")
    assert {ImpactDimension.COST, ImpactDimension.LATENCY} <= set(change.impacts)


def test_temperature_change_flags_behaviour() -> None:
    after = descriptor(inference={"temperature": 0.9})
    change = find(diff_descriptors(descriptor(), after).changes, "temperature")
    assert change.category is ChangeCategory.INFERENCE_PARAMS
    assert ImpactDimension.BEHAVIOUR in change.impacts


# ----------------------------------------------------------------- tools and MCP


def test_irreversible_write_tool_added_is_critical() -> None:
    after = descriptor()
    after["tools"].append(
        {"name": "payment_api", "kind": "http", "effect": "write", "reversible": False}
    )

    change = find(diff_descriptors(descriptor(), after).changes, "payment_api")

    assert change.category is ChangeCategory.TOOL
    assert change.severity is Severity.CRITICAL
    assert "irreversible" in change.summary


def test_read_only_tool_added_is_low_severity() -> None:
    after = descriptor()
    after["tools"].append(
        {"name": "lookup_policy", "kind": "http", "effect": "read", "reversible": True}
    )
    change = find(diff_descriptors(descriptor(), after).changes, "lookup_policy")
    assert change.severity is Severity.LOW


def test_tool_access_widened_from_read_to_write() -> None:
    before = descriptor(
        tools=[{"name": "claims_database", "kind": "mcp", "effect": "read", "reversible": True}]
    )
    change = find(diff_descriptors(before, descriptor()).changes, "effect")
    assert change.severity is Severity.CRITICAL
    assert change.detail is not None and "write" in change.detail


def test_mcp_server_digest_change_is_detected() -> None:
    """The server changed its tools underneath the agent. Nothing in the agent's own
    repository would show this, which is the point of tracking it."""
    after = descriptor()
    after["references"]["mcp_servers"][0]["digest"] = "sha256:m2"

    change = find(diff_descriptors(descriptor(), after).changes, "mcp_servers")

    assert change.category is ChangeCategory.MCP_SERVER
    assert change.severity is Severity.HIGH
    assert change.detail is not None and "repository" in change.detail


def test_mcp_server_added() -> None:
    after = descriptor()
    after["references"]["mcp_servers"].append(
        {"url": "https://mcp.acme/payments", "digest": "sha256:p1"}
    )
    change = find(diff_descriptors(descriptor(), after).changes, "payments")
    assert change.operation is ChangeOperation.ADDED


# ----------------------------------------------------------------- oversight


def test_removing_human_approval_is_critical() -> None:
    after = descriptor()
    after["capabilities"][1]["human_approval"] = "none"

    change = find(diff_descriptors(descriptor(), after).changes, "human_approval")

    assert change.category is ChangeCategory.OVERSIGHT
    assert change.severity is Severity.CRITICAL
    assert change.detail is not None and "weakened" in change.detail


def test_strengthening_human_approval_is_not_critical() -> None:
    before = descriptor()
    before["capabilities"][1]["human_approval"] = "conditional"
    change = find(diff_descriptors(before, descriptor()).changes, "human_approval")
    assert change.severity is Severity.MEDIUM


def test_raising_a_value_limit_is_high_severity() -> None:
    after = descriptor()
    after["capabilities"][1]["value_limit"]["max"] = 500000
    change = find(diff_descriptors(descriptor(), after).changes, "value_limit")
    assert change.severity is Severity.HIGH
    assert change.detail is not None and "exposure" in change.detail


def test_raising_autonomy_is_critical() -> None:
    after = descriptor(runtime={"autonomy": "autonomous"})
    change = find(diff_descriptors(descriptor(), after).changes, "autonomy")
    assert change.category is ChangeCategory.OVERSIGHT
    assert change.severity is Severity.CRITICAL


# ----------------------------------------------------------------- data and residency


def test_new_data_class_is_critical() -> None:
    after = descriptor()
    after["data"]["classes"] = ["customer_pii", "financial"]

    change = find(diff_descriptors(descriptor(), after).changes, "financial")
    assert change.category is ChangeCategory.DATA_CLASS
    assert change.severity is Severity.CRITICAL


def test_new_permitted_region_is_critical() -> None:
    after = descriptor()
    after["data"]["residency"]["permitted_regions"] = ["eu-west-1", "us-east-1"]
    change = find(diff_descriptors(descriptor(), after).changes, "us-east-1")
    assert change.category is ChangeCategory.RESIDENCY


def test_data_source_region_move_is_critical() -> None:
    after = descriptor()
    after["data"]["sources"][0]["region"] = "us-east-1"
    change = find(diff_descriptors(descriptor(), after).changes, "sources")
    assert change.category is ChangeCategory.RESIDENCY
    assert change.severity is Severity.CRITICAL


def test_removing_an_injection_defence_is_flagged_as_weakening() -> None:
    after = descriptor()
    after["security"]["prompt_injection_defences"] = ["input_classifier"]

    change = find(diff_descriptors(descriptor(), after).changes, "tool_allowlist")
    assert change.severity is Severity.HIGH
    assert change.detail is not None and "removed" in change.detail


def test_removing_a_data_class_is_benign() -> None:
    """Narrowing scope is not a weakening, unlike removing a control."""
    before = descriptor()
    before["data"]["classes"] = ["customer_pii", "financial"]
    change = find(diff_descriptors(before, descriptor()).changes, "financial")
    assert change.severity is Severity.LOW


# ----------------------------------------------------------------- prompts, delegation


def test_prompt_edit_is_reported_by_digest_only() -> None:
    """The differ must not need an embedding model — it has to run in CI offline."""
    after = descriptor(prompts=[{"name": "system", "digest": "sha256:bbb"}])

    change = find(diff_descriptors(descriptor(), after).changes, "prompts")

    assert change.category is ChangeCategory.PROMPT
    assert change.before_value == {"digest": "sha256:aaa"}
    assert "edited" in change.summary


def test_delegation_to_unaccredited_agent_is_critical() -> None:
    after = descriptor(
        delegates_to=[{"urn": "urn:aap:acme:third-party:scoring", "trust": "external"}]
    )
    change = find(diff_descriptors(descriptor(), after).changes, "delegates_to")
    assert change.category is ChangeCategory.DELEGATION
    assert change.severity is Severity.CRITICAL


def test_delegation_to_accredited_agent_is_high_not_critical() -> None:
    after = descriptor(
        delegates_to=[{"urn": "urn:aap:acme:fraud:scoring", "trust": "internal_accredited"}]
    )
    change = find(diff_descriptors(descriptor(), after).changes, "delegates_to")
    assert change.severity is Severity.HIGH


def test_ownership_handover_is_tracked() -> None:
    after = descriptor(accountability={"accountable_person": "person:s.rao@acme.com"})
    change = find(diff_descriptors(descriptor(), after).changes, "accountable_person")
    assert change.category is ChangeCategory.METADATA
    assert ImpactDimension.COMPLIANCE in change.impacts


# ----------------------------------------------------------------- aggregate view


def test_realistic_release_groups_and_summarises() -> None:
    """The end-to-end shape a release page renders from."""
    after = descriptor()
    after["agent"]["version"] = "3.5.0"
    after["models"][0]["provider"] = "openai"
    after["models"][0]["family"] = "gpt"
    after["resilience"] = {"request_timeout_ms": 15000, "max_retries": 3}
    after["tools"].append(
        {"name": "payment_api", "kind": "http", "effect": "write", "reversible": False}
    )
    after["prompts"] = [{"name": "system", "digest": "sha256:ccc"}]

    diff = diff_descriptors(descriptor(), after)

    assert len(diff.changes) >= 5

    grouped = diff.grouped()
    assert ChangeCategory.MODEL in grouped
    assert ChangeCategory.RESILIENCE in grouped
    assert ChangeCategory.TOOL in grouped
    assert ChangeCategory.PROMPT in grouped

    # Categories come back in enum display order, not in discovery order.
    assert list(grouped) == [c for c in ChangeCategory if c in grouped]

    assert {ImpactDimension.COMPLIANCE, ImpactDimension.SECURITY} <= diff.impacts
    assert "change" in diff.headline()

    # Every change carries a complete sentence, not a field dump.
    for change in diff.changes:
        assert change.summary.endswith(".")
        assert change.subject


def test_composition_skill_reorder_is_silent() -> None:
    comp = {
        "skills": [
            {"name": "b_skill", "path": "a", "digest": "sha256:" + "a" * 64},
            {"name": "a_skill", "path": "b", "digest": "sha256:" + "b" * 64},
        ]
    }
    before = descriptor(composition=comp)
    after = descriptor(
        composition={
            "skills": [
                {"name": "a_skill", "path": "b", "digest": "sha256:" + "b" * 64},
                {"name": "b_skill", "path": "a", "digest": "sha256:" + "a" * 64},
            ]
        }
    )
    assert diff_descriptors(before, after).changes == []


def test_composition_skill_rename_not_add_remove() -> None:
    digest = "sha256:" + "c" * 64
    before = descriptor(
        composition={"skills": [{"name": "refund", "path": "skills/refund", "digest": digest}]}
    )
    after = descriptor(
        composition={"skills": [{"name": "refunds", "path": "skills/refund", "digest": digest}]}
    )
    changes = diff_descriptors(before, after).changes
    assert len(changes) == 1
    assert changes[0].operation is ChangeOperation.RENAMED
    assert "refund" in changes[0].summary and "refunds" in changes[0].summary


def test_composition_unknown_attribute_defaults_to_high_severity() -> None:
    before = descriptor(
        composition={"configs": [{"name": "app", "digest": "sha256:" + "d" * 64, "value": "a"}]}
    )
    after = descriptor(
        composition={"configs": [{"name": "app", "digest": "sha256:" + "e" * 64, "value": "b"}]}
    )
    change = find(diff_descriptors(before, after).changes, "composition.configs")
    assert change.severity is Severity.HIGH


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
