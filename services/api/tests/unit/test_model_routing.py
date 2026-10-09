"""Unit tests for model routing resolution and gateway config emission."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.domains.engagements.schemas import CrossBorderTransfer
from app.domains.model_routing.schemas import (
    AllowedDeployment,
    CompiledModelPolicy,
    EnforcementLevel,
    ModelSelectionMode,
)
from app.domains.model_routing.service import (
    build_litellm_config,
    config_enforces_fallback_access,
    cross_border_permits,
    evaluate_model_access,
    verify_emitted_config,
)
from app.domains.policy.schemas import DecisionOutcome
from app.domains.registry.schemas import LifecycleState


def _base_policy() -> dict[str, object]:
    return {
        "selection_mode": "allowlist",
        "allowlist": ["anthropic/claude-sonnet-4"],
    }


def test_production_denies_unknown_model() -> None:
    outcome, reason, _, _ = evaluate_model_access(
        provider="anthropic",
        model_id="unknown-model",
        environment=LifecycleState.PRODUCTION.value,
        selection_mode=ModelSelectionMode.ALLOWLIST,
        model_policy=_base_policy(),
        permitted_regions=frozenset({"eu-west-1"}),
        engagement_cross_border=CrossBorderTransfer.PROHIBITED,
        descriptor_residency={"permitted_regions": ["eu-west-1"]},
        catalog_region=None,
        catalog_jurisdiction=None,
        has_catalog_entry=False,
        catalog_classified=False,
        data_classes=["customer_pii"],
        lawful_basis={},
        dev_permissive=False,
    )
    assert outcome is DecisionOutcome.DENY
    assert reason == "model_unknown"


def test_dev_environment_allows_unknown_when_permissive() -> None:
    outcome, reason, _, _ = evaluate_model_access(
        provider="anthropic",
        model_id="unknown-model",
        environment=LifecycleState.DEV.value,
        selection_mode=ModelSelectionMode.ALLOWLIST,
        model_policy=_base_policy(),
        permitted_regions=frozenset({"eu-west-1"}),
        engagement_cross_border=CrossBorderTransfer.PROHIBITED,
        descriptor_residency={},
        catalog_region=None,
        catalog_jurisdiction=None,
        has_catalog_entry=False,
        catalog_classified=False,
        data_classes=[],
        lawful_basis={},
        dev_permissive=True,
    )
    assert outcome is DecisionOutcome.ALLOW
    assert reason == "model_unknown_dev"


def test_in_region_classified_model_allowed() -> None:
    outcome, reason, _, region = evaluate_model_access(
        provider="anthropic",
        model_id="claude-sonnet-4",
        environment=LifecycleState.PRODUCTION.value,
        selection_mode=ModelSelectionMode.ALLOWLIST,
        model_policy=_base_policy(),
        permitted_regions=frozenset({"eu-west-1"}),
        engagement_cross_border=CrossBorderTransfer.PROHIBITED,
        descriptor_residency={"permitted_regions": ["eu-west-1"]},
        catalog_region="eu-west-1",
        catalog_jurisdiction="EU",
        has_catalog_entry=True,
        catalog_classified=True,
        data_classes=["operational"],
        lawful_basis={},
        dev_permissive=False,
    )
    assert outcome is DecisionOutcome.ALLOW
    assert reason == "allowed"
    assert region == "eu-west-1"


@pytest.mark.parametrize(
    ("rung", "basis", "lawful", "model_j", "expect_ok", "expect_reason"),
    [
        (CrossBorderTransfer.PROHIBITED, None, False, "US", False, "cross_border_prohibited"),
        (
            CrossBorderTransfer.PERMITTED_WITH_SAFEGUARDS,
            "gdpr_art_46",
            False,
            "US",
            True,
            "cross_border_safeguards",
        ),
        (
            CrossBorderTransfer.PERMITTED_WITH_SAFEGUARDS,
            None,
            False,
            "US",
            False,
            "cross_border_safeguards_missing",
        ),
        (
            CrossBorderTransfer.PERMITTED_WITH_CONSENT,
            None,
            True,
            "US",
            True,
            "cross_border_consent",
        ),
        (CrossBorderTransfer.PERMITTED, None, False, "US", True, "cross_border_permitted"),
    ],
)
def test_cross_border_ladder_rungs(
    rung: CrossBorderTransfer,
    basis: str | None,
    lawful: bool,
    model_j: str,
    expect_ok: bool,
    expect_reason: str,
) -> None:
    ok, reason = cross_border_permits(
        rung,
        descriptor_basis=basis,
        lawful_basis_present=lawful,
        home_jurisdictions=frozenset({"EU"}),
        model_jurisdiction=model_j,
    )
    assert ok is expect_ok
    assert reason == expect_reason


def test_emitted_config_enforces_fallback_access() -> None:
    compiled = CompiledModelPolicy(
        agent_id=uuid4(),
        agent_version_id=uuid4(),
        engagement_id=None,
        selection_mode=ModelSelectionMode.PINNED,
        allowed_deployments=(
            AllowedDeployment(
                catalog_entry_id=uuid4(),
                provider="anthropic",
                model_id="claude-sonnet-4",
                region_name="eu-west-1",
                jurisdiction="EU",
            ),
        ),
        allowed_patterns=("anthropic/claude-sonnet-4",),
        permitted_regions=frozenset({"eu-west-1"}),
        cross_border_rung=CrossBorderTransfer.PROHIBITED,
        enforcement_level=EnforcementLevel.BLOCKING,
        virtual_key_ref="vk-test",
        compiled_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        rules_digest="sha256:abc",
    )
    emitted = build_litellm_config(compiled)
    assert config_enforces_fallback_access(emitted.config)
    assert emitted.fallback_access_enforced is True
    assert verify_emitted_config(emitted.config) == []


def test_verify_emitted_config_flags_missing_fallback_enforcement() -> None:
    gaps = verify_emitted_config({"general_settings": {}, "router_settings": {}})
    assert "enforce_fallback_model_access" in gaps[0]
