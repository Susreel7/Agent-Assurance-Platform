"""Materiality engine tests.

The rules engine makes the product's central claim: *this change does not invalidate the
approval, and here is the named reason why*. Every assertion in this file is a claim the
platform will make to a customer's security reviewer, so the cost of a wrong verdict is
asymmetric and specific:

  * a false **immaterial** ships an unreviewed change under a live approval, which is the
    exact failure the product is sold to prevent;
  * a false **material** suspends an approval over a typo, and an engine that cries wolf
    gets switched off.

Tests run through ``diff_descriptors`` rather than hand-built ``SemanticChange`` objects
wherever possible. That is deliberate: a rule that is right about a change the differ
never emits is worth nothing, so the differ and the rules are pinned together.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domains.materiality.rules import (
    ALL_RULES,
    MaterialityContext,
    apply_verdicts,
    assess_diff,
    describe_rule,
    evaluate_change,
)
from app.domains.releases.differ import diff_descriptors
from app.domains.releases.schemas import (
    AccreditationImpact,
    ChangeCategory,
    ChangeOperation,
    Materiality,
    SemanticChange,
    Severity,
)


def descriptor(**overrides: Any) -> dict[str, Any]:
    """An accredited baseline: EU-only, supervised, PII, one write tool under approval."""
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


APPROVED = MaterialityContext(
    approved_data_classes=frozenset({"customer_pii"}),
    approved_regions=frozenset({"eu-west-1"}),
)
"""Context matching the baseline above — what an accredited agent's scope looks like."""


def assess(before: dict[str, Any], after: dict[str, Any], ctx: MaterialityContext = APPROVED):
    return assess_diff(diff_descriptors(before, after), ctx)


def rule_ids(assessment) -> set[str]:
    return {r for change in assessment.changes for r in change.rules_fired}


# ----------------------------------------------------------------------
# The central claim: verdict determines accreditation consequence
# ----------------------------------------------------------------------


def test_no_change_leaves_the_approval_standing() -> None:
    result = assess(descriptor(), descriptor())
    assert result.verdict is Materiality.IMMATERIAL
    assert result.accreditation_impact is AccreditationImpact.NONE


def test_a_material_change_suspends_the_approval() -> None:
    """The demo path. Swapping model provider must suspend, not merely flag."""
    after = descriptor(
        models=[
            {
                "provider": "openai",
                "family": "gpt",
                "id": "gpt-4o",
                "hosting": "vendor_api",
                "endpoint_region": "eu-west-1",
                "role": "primary",
            }
        ]
    )
    result = assess(descriptor(), after)

    assert result.verdict is Materiality.MATERIAL
    assert result.accreditation_impact is AccreditationImpact.SUSPENDS
    assert "MAT-001-model-provider" in rule_ids(result)


def test_a_review_change_requires_revalidation_not_suspension() -> None:
    """An added MCP server is not proof of harm, but nobody can claim it is safe either.
    Conflating this with suspension would make the engine unusable."""
    after = descriptor(
        references={
            "mcp_servers": [
                {"url": "https://mcp.acme/claims", "digest": "sha256:m1"},
                {"url": "https://mcp.partner/pricing", "digest": "sha256:m2"},
            ]
        }
    )
    result = assess(descriptor(), after)

    assert result.verdict is Materiality.NEEDS_REVIEW
    assert result.accreditation_impact is AccreditationImpact.REQUIRES_REVALIDATION


def test_material_outranks_review_in_the_same_release() -> None:
    """A release carrying both must suspend. Reporting the milder verdict would let a
    material change ride along behind a review item."""
    after = descriptor(
        models=[
            {
                "provider": "openai",
                "family": "gpt",
                "id": "gpt-4o",
                "hosting": "vendor_api",
                "endpoint_region": "eu-west-1",
                "role": "primary",
            }
        ],
        runtime={"framework": "crewai"},
    )
    result = assess(descriptor(), after)

    assert result.verdict is Materiality.MATERIAL
    assert result.accreditation_impact is AccreditationImpact.SUSPENDS


# ----------------------------------------------------------------------
# Residency and data scope — the questions clients actually ask
# ----------------------------------------------------------------------


def test_moving_a_model_outside_the_approved_region_is_material() -> None:
    after = descriptor(
        models=[
            {
                "provider": "anthropic",
                "family": "claude",
                "id": "claude-sonnet-4-5",
                "hosting": "vendor_api",
                "endpoint_region": "us-east-1",
                "role": "primary",
            }
        ]
    )
    result = assess(descriptor(), after)

    assert result.verdict is Materiality.MATERIAL
    assert "MAT-004-model-region" in rule_ids(result)


def test_touching_a_new_data_class_is_material() -> None:
    after = descriptor(data={"classes": ["customer_pii", "payment_card"]})
    result = assess(descriptor(), after)

    assert result.verdict is Materiality.MATERIAL
    assert "MAT-006-data-class-added" in rule_ids(result)


def test_no_longer_touching_a_data_class_is_immaterial() -> None:
    """Narrowing scope cannot invalidate an approval granted over the wider one. The
    symmetric case is where naive engines produce their most damaging false positives."""
    before = descriptor(data={"classes": ["customer_pii", "payment_card"]})
    result = assess(before, descriptor())

    assert result.verdict is Materiality.IMMATERIAL
    assert result.accreditation_impact is AccreditationImpact.NONE


def _with_cross_border(stance: str) -> dict[str, Any]:
    return descriptor(
        data={"residency": {"permitted_regions": ["eu-west-1"], "cross_border": stance}}
    )


def test_loosening_cross_border_transfer_is_material() -> None:
    assert assess(descriptor(), _with_cross_border("permitted")).verdict is Materiality.MATERIAL


def test_tightening_cross_border_transfer_is_immaterial() -> None:
    before = _with_cross_border("permitted")
    assert assess(before, descriptor()).verdict is Materiality.IMMATERIAL


# Q-007 / D-020: safeguards and consent are separate rungs. Before they were split, a
# move between them produced no ladder movement and no verdict, so an agent could swap
# Article 46 safeguards for Article 49 consent under a live accreditation and the gate
# would see nothing.


def test_swapping_safeguards_for_consent_is_material() -> None:
    """Still legal, no longer protected. Consent authorises a transfer and then protects
    nothing, so dropping safeguards for it is a loosening a reviewer must see."""
    before = _with_cross_border("permitted_with_safeguards")
    after = _with_cross_border("permitted_with_consent")

    result = assess(before, after)
    assert result.verdict is Materiality.MATERIAL
    assert "MAT-009-cross-border-loosened" in rule_ids(result)


def test_replacing_consent_with_safeguards_is_immaterial() -> None:
    """The strengthening direction. Adding enforceable protection must not cost a
    re-accreditation, or nobody will do it."""
    before = _with_cross_border("permitted_with_consent")
    after = _with_cross_border("permitted_with_safeguards")

    assert assess(before, after).verdict is Materiality.IMMATERIAL


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("prohibited", "permitted_with_safeguards"),
        ("prohibited", "permitted_with_consent"),
        ("permitted_with_safeguards", "permitted"),
        ("permitted_with_consent", "permitted"),
    ],
)
def test_every_step_up_the_cross_border_ladder_is_material(before: str, after: str) -> None:
    result = assess(_with_cross_border(before), _with_cross_border(after))
    assert result.verdict is Materiality.MATERIAL, f"{before} -> {after} was not material"


def test_article_46_instruments_land_on_the_safeguards_rung() -> None:
    """Descriptors say `permitted_with_scc` or `permitted_with_bcr`. Both are Article 46
    instruments, so neither is a change when compared against `permitted_with_safeguards`.
    An unmapped spelling would fall off the ladder and escalate to review instead."""
    for spelling in ("permitted_with_scc", "permitted_with_bcr", "with_safeguards"):
        result = assess(
            _with_cross_border("permitted_with_safeguards"), _with_cross_border(spelling)
        )
        assert result.verdict is Materiality.IMMATERIAL, spelling


def test_consent_spellings_land_on_the_consent_rung_not_safeguards() -> None:
    """The regression risk of the split: leaving a consent spelling mapped to safeguards
    would silently restore the old collapsed behaviour for that spelling alone."""
    result = assess(
        _with_cross_border("permitted_with_safeguards"), _with_cross_border("explicit_consent")
    )
    assert result.verdict is Materiality.MATERIAL


def test_extending_retention_is_material_but_shortening_is_not() -> None:
    """Both directions in one test because the asymmetry *is* the rule. An engine that
    treats any retention edit as material would flag every privacy improvement."""
    longer = descriptor(data={"retention_days": 365})
    shorter = descriptor(data={"retention_days": 7})

    assert assess(descriptor(), longer).verdict is Materiality.MATERIAL
    assert assess(descriptor(), shorter).verdict is Materiality.IMMATERIAL


# ----------------------------------------------------------------------
# Authority and oversight
# ----------------------------------------------------------------------


def test_removing_a_human_approval_requirement_is_material() -> None:
    after = descriptor(
        capabilities=[
            {"name": "read_claim", "effect": "read", "reversible": True, "human_approval": "none"},
            {
                "name": "approve_claim",
                "effect": "write",
                "reversible": False,
                "human_approval": "none",
                "value_limit": {"currency": "EUR", "max": 5000},
            },
        ]
    )
    result = assess(descriptor(), after)

    assert result.verdict is Materiality.MATERIAL
    assert "MAT-013-oversight-removed" in rule_ids(result)


def test_raising_a_value_limit_is_material_but_lowering_is_not() -> None:
    def with_limit(maximum: int) -> dict[str, Any]:
        return descriptor(
            capabilities=[
                {
                    "name": "read_claim",
                    "effect": "read",
                    "reversible": True,
                    "human_approval": "none",
                },
                {
                    "name": "approve_claim",
                    "effect": "write",
                    "reversible": False,
                    "human_approval": "required",
                    "value_limit": {"currency": "EUR", "max": maximum},
                },
            ]
        )

    assert assess(descriptor(), with_limit(500_000)).verdict is Materiality.MATERIAL
    assert assess(descriptor(), with_limit(100)).verdict is Materiality.IMMATERIAL


def test_raising_autonomy_is_material_but_lowering_is_not() -> None:
    """Uses the AAP 0.1 ``runtime.autonomy`` vocabulary: supervised, semi_autonomous,
    autonomous."""
    autonomous = descriptor(runtime={"autonomy": "autonomous"})
    assert assess(descriptor(), autonomous).verdict is Materiality.MATERIAL

    assert assess(autonomous, descriptor()).verdict is Materiality.IMMATERIAL


def test_rewording_autonomy_without_changing_it_is_immaterial() -> None:
    """``human_in_the_loop`` and ``supervised`` are the same rung. A descriptor that
    switches spelling has not changed what the agent may do, and suspending an approval
    over a rename is how an engine loses its audience."""
    reworded = descriptor(runtime={"autonomy": "human_in_the_loop"})
    result = assess(descriptor(), reworded)

    assert result.verdict is Materiality.IMMATERIAL
    assert "IMM-019-vocabulary-equivalent" in rule_ids(result)


def test_an_unrecognised_autonomy_value_escalates_rather_than_passing() -> None:
    """The dangerous case. An unknown word for "fully autonomous" must not slip through
    because neither ladder rule could place it."""
    unknown = descriptor(runtime={"autonomy": "yolo_mode"})
    result = assess(descriptor(), unknown)

    assert result.verdict is Materiality.NEEDS_REVIEW
    assert "REV-017-vocabulary-unknown" in rule_ids(result)


def test_removing_an_injection_defence_is_material() -> None:
    after = descriptor(
        security={
            "authentication": "oauth2_client_credentials",
            "prompt_injection_defences": ["input_classifier"],
        }
    )
    result = assess(descriptor(), after)

    assert result.verdict is Materiality.MATERIAL
    assert "MAT-014-guardrail-removed" in rule_ids(result)


def test_adding_an_injection_defence_is_immaterial() -> None:
    after = descriptor(
        security={
            "authentication": "oauth2_client_credentials",
            "prompt_injection_defences": ["input_classifier", "tool_allowlist", "output_filter"],
        }
    )
    assert assess(descriptor(), after).verdict is Materiality.IMMATERIAL


def test_weakening_authentication_is_material() -> None:
    after = descriptor(
        security={
            "authentication": "api_key",
            "prompt_injection_defences": ["input_classifier", "tool_allowlist"],
        }
    )
    assert assess(descriptor(), after).verdict is Materiality.MATERIAL


# ----------------------------------------------------------------------
# The cases that must NOT fire — protecting the engine's credibility
# ----------------------------------------------------------------------


def test_a_model_point_version_bump_is_immaterial() -> None:
    """The single most common real change. If this suspended approvals the product
    would be uninstalled within a week."""
    after = descriptor(
        models=[
            {
                "provider": "anthropic",
                "family": "claude",
                "id": "claude-sonnet-4-5-20250101",
                "hosting": "vendor_api",
                "endpoint_region": "eu-west-1",
                "role": "primary",
            }
        ]
    )
    result = assess(descriptor(), after)

    assert result.verdict is not Materiality.MATERIAL
    assert result.accreditation_impact is not AccreditationImpact.SUSPENDS


def test_descriptive_metadata_changes_are_immaterial() -> None:
    after = descriptor(
        accountability={
            "owning_team": "Claims Automation",
            "accountable_person": "person:j.doe@acme.com",
        }
    )
    result = assess(descriptor(), after)

    assert result.verdict is Materiality.IMMATERIAL
    assert result.accreditation_impact is AccreditationImpact.NONE


def test_tightening_resilience_is_immaterial() -> None:
    after = descriptor(resilience={"request_timeout_ms": 15000, "max_retries": 5})
    assert assess(descriptor(), after).verdict is Materiality.IMMATERIAL


def test_lowering_temperature_is_immaterial() -> None:
    after = descriptor(inference={"temperature": 0.0, "max_tokens": 4096})
    assert assess(descriptor(), after).verdict is Materiality.IMMATERIAL


def test_removing_a_tool_is_immaterial() -> None:
    assert assess(descriptor(), descriptor(tools=[])).verdict is Materiality.IMMATERIAL


# ----------------------------------------------------------------------
# Context sensitivity
# ----------------------------------------------------------------------


def test_a_critical_cve_in_a_component_is_material() -> None:
    """The fact comes from the assurance domain rather than the diff, which is why
    context exists at all."""
    change = SemanticChange(
        category=ChangeCategory.DEPENDENCY,
        operation=ChangeOperation.ADDED,
        path="bom.components[langchain]",
        subject="langchain",
        before_value=None,
        after_value={"name": "langchain", "version": "0.3.1"},
        summary="Added langchain 0.3.1",
        severity=Severity.MEDIUM,
    )
    ctx = MaterialityContext(critical_cve_components=frozenset({"langchain@0.3.1"}))

    verdict = evaluate_change(change, ctx)
    assert verdict.verdict is Materiality.MATERIAL
    assert "MAT-015-critical-cve" in verdict.rules_fired


def test_an_empty_context_errs_towards_review_not_approval() -> None:
    """Defaults are pessimistic by design. Calling the engine without knowing an agent's
    approved scope must not produce a confident "immaterial"."""
    after = descriptor(
        tools=[
            {"name": "claims_database", "kind": "mcp", "effect": "write", "reversible": True},
            {"name": "pricing_lookup", "kind": "http", "effect": "read", "reversible": True},
        ]
    )
    bare = assess(descriptor(), after, MaterialityContext())
    scoped = assess(descriptor(), after, APPROVED)

    assert bare.accreditation_impact is not AccreditationImpact.NONE
    assert scoped.accreditation_impact is AccreditationImpact.NONE


def test_an_override_can_reverse_a_verdict() -> None:
    """How a customer's adjudication tunes the engine. Without this, a reviewer who
    disagrees once has to disagree every release."""
    after = descriptor(
        references={
            "mcp_servers": [
                {"url": "https://mcp.acme/claims", "digest": "sha256:m1"},
                {"url": "https://mcp.partner/pricing", "digest": "sha256:m2"},
            ]
        }
    )
    before_override = assess(descriptor(), after)
    assert before_override.verdict is Materiality.NEEDS_REVIEW

    tuned = MaterialityContext(
        approved_data_classes=APPROVED.approved_data_classes,
        approved_regions=APPROVED.approved_regions,
        overrides={"REV-006-mcp-server-added": Materiality.IMMATERIAL},
    )
    assert assess(descriptor(), after, tuned).verdict is Materiality.IMMATERIAL


# ----------------------------------------------------------------------
# Robustness — the engine sits in a CI gate and must not be the thing that breaks
# ----------------------------------------------------------------------


def test_every_change_receives_exactly_one_verdict() -> None:
    """No change may emerge unruled. An unruled change would be silently dropped from
    the release view, which is worse than a wrong verdict because nobody sees it."""
    after = descriptor(
        models=[
            {
                "provider": "openai",
                "family": "gpt",
                "id": "gpt-4o",
                "hosting": "self_hosted",
                "endpoint_region": "us-east-1",
                "role": "primary",
            }
        ],
        data={"classes": ["customer_pii", "health"], "retention_days": 90},
        runtime={"autonomy": "autonomous", "framework": "crewai"},
        tools=[],
    )
    result = assess(descriptor(), after)

    assert result.changes
    for change in result.changes:
        assert change.verdict in set(Materiality)
        assert change.rules_fired, f"{change.path} fired no rule"


def test_a_malformed_descriptor_does_not_raise() -> None:
    """A predicate that trips over an unexpected shape must not take the CI gate down.
    An agent whose descriptor is odd still needs a verdict."""
    broken = descriptor(models=["not-a-mapping"], data={"classes": "customer_pii"})
    result = assess(descriptor(), broken)

    assert result.verdict in set(Materiality)


@pytest.mark.parametrize("verdict", list(Materiality))
def test_impact_mapping_is_total(verdict: Materiality) -> None:
    """Every verdict maps to a defined consequence, so a new verdict cannot be added
    without deciding what it does to an approval."""
    expected = {
        Materiality.MATERIAL: AccreditationImpact.SUSPENDS,
        Materiality.NEEDS_REVIEW: AccreditationImpact.REQUIRES_REVALIDATION,
        Materiality.IMMATERIAL: AccreditationImpact.NONE,
    }
    assert verdict in expected


# ----------------------------------------------------------------------
# The rule set itself
# ----------------------------------------------------------------------


def test_rule_ids_are_unique() -> None:
    """Ids are the public handle on a verdict and they are stored on release rows.

    A collision means RULES_BY_ID silently drops one rule, so a stored verdict resolves
    to the wrong explanation — and the rule that lost still fires, invisibly.
    """
    ids = [rule.id for rule in ALL_RULES]
    duplicates = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
    assert not duplicates


def test_every_fired_rule_is_resolvable() -> None:
    """Verdicts persist and rule sets evolve, so a release ruled last quarter must still
    be explainable. Every id the engine can emit has to resolve, including the fallbacks
    that are deliberately kept out of evaluation."""
    for rule in ALL_RULES:
        assert describe_rule(rule.id) is not None, rule.id

    for fallback in ("REV-000-unclassified", "IMM-000-no-assurance-impact"):
        assert describe_rule(fallback) is not None, fallback
        assert fallback not in {rule.id for rule in ALL_RULES}


def test_every_rule_carries_a_rationale() -> None:
    """A rule id without a sentence behind it cannot be put in front of a reviewer."""
    for rule in ALL_RULES:
        assert rule.rationale.strip(), rule.id


def test_an_unknown_rule_id_resolves_to_nothing_rather_than_raising() -> None:
    assert describe_rule("MAT-999-does-not-exist") is None


def test_unclassified_composition_change_is_not_immaterial() -> None:
    """High-severity composition edits must not fall through to IMM-000-no-assurance-impact."""
    before = descriptor(
        composition={"configs": [{"name": "app", "digest": "sha256:" + "a" * 64, "value": "1"}]}
    )
    after = descriptor(
        composition={"configs": [{"name": "app", "digest": "sha256:" + "b" * 64, "value": "2"}]}
    )
    ruled = apply_verdicts(diff_descriptors(before, after).changes)
    assert ruled
    assert all(c.verdict is not Materiality.IMMATERIAL for c in ruled)
