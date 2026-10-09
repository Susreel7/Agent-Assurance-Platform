"""Unit tests for policy evaluation and digest stability."""

from __future__ import annotations

from uuid import uuid4

from app.domains.policy.schemas import DecisionOutcome, EvaluationRequest, RuleSet, ToolAllowRule
from app.domains.policy.service import (
    DEFAULT_RESIDENCY_POLICY_YAML,
    evaluate_rules,
    parse_rules_yaml,
    rules_digest,
)


def test_digest_stable_for_same_rules() -> None:
    first = parse_rules_yaml(DEFAULT_RESIDENCY_POLICY_YAML)
    second = parse_rules_yaml(DEFAULT_RESIDENCY_POLICY_YAML)
    assert rules_digest(first) == rules_digest(second)


def test_tool_not_on_allowlist_denies() -> None:
    rules = RuleSet(tool_allowlist=ToolAllowRule(id="tools.test", allowed_tools=["safe_tool"]))
    result = evaluate_rules(
        rules,
        EvaluationRequest(tool_name="dangerous_tool"),
    )
    assert result.outcome is DecisionOutcome.DENY
    assert result.rule_id == "tools.test"


def test_special_category_without_lawful_basis_denies() -> None:
    rules = parse_rules_yaml(DEFAULT_RESIDENCY_POLICY_YAML)
    result = evaluate_rules(
        rules,
        EvaluationRequest(data_classes=["customer_pii"], requested_region="eu-west-1"),
    )
    assert result.outcome is DecisionOutcome.DENY
    assert result.reason_code == "special_category_no_lawful_basis"


def test_region_reroute_when_alternate_permitted() -> None:
    rules = parse_rules_yaml(DEFAULT_RESIDENCY_POLICY_YAML)
    result = evaluate_rules(
        rules,
        EvaluationRequest(
            data_classes=["operational"],
            requested_region="us-west-2",
            lawful_basis={"operational": "contract"},
        ),
    )
    assert result.outcome is DecisionOutcome.REROUTE
    assert result.effective_region == "us-east-1"


def test_oversight_action_requires_approval() -> None:
    rules = parse_rules_yaml(DEFAULT_RESIDENCY_POLICY_YAML)
    result = evaluate_rules(
        rules,
        EvaluationRequest(action_class="approve_payment", lawful_basis={"operational": "contract"}),
    )
    assert result.outcome is DecisionOutcome.REQUIRE_APPROVAL


def test_allow_when_no_rule_fires() -> None:
    rules = RuleSet()
    result = evaluate_rules(
        rules,
        EvaluationRequest(agent_id=uuid4(), requested_region="eu-west-1"),
    )
    assert result.outcome is DecisionOutcome.ALLOW
