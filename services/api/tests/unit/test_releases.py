"""Release pure-function tests — state machine and CI gate verdict."""

from __future__ import annotations

from app.domains.materiality.rules import assess_diff
from app.domains.releases.differ import diff_descriptors
from app.domains.releases.schemas import (
    AccreditationImpact,
    ChangeCategory,
    ChangeOperation,
    ImpactDimension,
    Materiality,
    ReleaseDiff,
    ReleaseState,
    SemanticChange,
    Severity,
)
from app.domains.releases.service import (
    build_gate_verdict,
    can_transition,
    preview_release,
    provisional_verdict,
)


def test_gate_blocks_on_material_changes() -> None:
    diff = ReleaseDiff(
        from_semver="1.0.0",
        to_semver="1.1.0",
        changes=[
            SemanticChange(
                category=ChangeCategory.MODEL,
                operation=ChangeOperation.MODIFIED,
                path="models[role=primary].provider",
                subject="Primary model provider",
                summary="Provider changed.",
                verdict=Materiality.MATERIAL,
                severity=Severity.CRITICAL,
                impacts=frozenset({ImpactDimension.COMPLIANCE}),
            )
        ],
    )
    verdict = build_gate_verdict(diff)
    assert verdict.allowed is False
    assert verdict.material_count == 1
    assert verdict.accreditation_impact is AccreditationImpact.SUSPENDS


def test_gate_allows_imaterial_only() -> None:
    diff = ReleaseDiff(
        from_semver="1.0.0",
        to_semver="1.0.1",
        changes=[
            SemanticChange(
                category=ChangeCategory.METADATA,
                operation=ChangeOperation.MODIFIED,
                path="accountability.owning_team",
                subject="Owning team",
                summary="Team renamed.",
                verdict=Materiality.IMMATERIAL,
            )
        ],
    )
    verdict = build_gate_verdict(diff)
    assert verdict.allowed is True
    assert verdict.accreditation_impact is AccreditationImpact.NONE


def test_state_machine_happy_path() -> None:
    assert can_transition(ReleaseState.DRAFT, ReleaseState.PROPOSED)
    assert can_transition(ReleaseState.PROPOSED, ReleaseState.APPROVED)
    assert can_transition(ReleaseState.APPROVED, ReleaseState.ROLLED_OUT)
    assert can_transition(ReleaseState.ROLLED_OUT, ReleaseState.ROLLED_BACK)


def test_state_machine_rejects_skip() -> None:
    assert not can_transition(ReleaseState.DRAFT, ReleaseState.APPROVED)


def test_provisional_verdict_marks_critical_as_material() -> None:
    change = SemanticChange(
        category=ChangeCategory.RESIDENCY,
        operation=ChangeOperation.MODIFIED,
        path="data.residency.cross_border",
        subject="Cross-border transfer stance",
        summary="Stance changed.",
        severity=Severity.CRITICAL,
    )
    assert provisional_verdict(change) is Materiality.MATERIAL


# ----------------------------------------------------------------------
# The CI gate and the console must agree
# ----------------------------------------------------------------------


def _baseline() -> dict[str, object]:
    return {
        "aap_version": "0.1",
        "agent": {"urn": "urn:aap:acme:x:y", "version": "1.0.0", "lifecycle_state": "production"},
        "runtime": {"autonomy": "supervised"},
        "models": [
            {
                "provider": "anthropic",
                "family": "claude",
                "id": "claude-sonnet-4-5",
                "endpoint_region": "eu-west-1",
                "role": "primary",
            }
        ],
        "data": {"classes": ["customer_pii"], "retention_days": 30},
    }


def test_gate_uses_the_materiality_engine_not_a_severity_heuristic() -> None:
    """The gate's verdict must carry named rule ids.

    A verdict without a rule id cannot be explained to a reviewer or adjudicated by one,
    and it is the signature of the severity-only fallback having been used.
    """
    after = {**_baseline(), "runtime": {"autonomy": "autonomous"}}
    verdict = preview_release(_baseline(), after)

    assert verdict.allowed is False
    assert verdict.blocking_changes
    fired = {r for c in verdict.blocking_changes for r in c.rules_fired}
    assert "MAT-016-autonomy-raised" in fired


def test_gate_advisory_names_the_blocking_rule() -> None:
    """An exit code says an engineer is blocked. A rule id says what to do about it."""
    after = {**_baseline(), "data": {"classes": ["customer_pii", "payment_card"]}}
    verdict = preview_release(_baseline(), after)

    assert verdict.allowed is False
    assert any("MAT-006-data-class-added" in line for line in verdict.advisory)


def test_gate_verdict_matches_a_direct_engine_assessment() -> None:
    """The regression this guards against is the one that was actually there: the gate
    ran a severity heuristic while the console ran the rule set, so the two disagreed on
    the same change."""
    after = {**_baseline(), "runtime": {"autonomy": "autonomous"}}

    gate = preview_release(_baseline(), after)
    engine = assess_diff(diff_descriptors(_baseline(), after))

    assert gate.accreditation_impact is engine.accreditation_impact
    assert gate.material_count == engine.material_count
    assert gate.review_count == engine.review_count


def test_gate_allows_a_change_the_engine_clears() -> None:
    """A metadata-only edit must not block a deploy. The gate being noisy is how it gets
    removed from a pipeline."""
    after = {**_baseline(), "data": {"classes": ["customer_pii"], "retention_days": 7}}
    verdict = preview_release(_baseline(), after)

    assert verdict.allowed is True
    assert verdict.accreditation_impact is AccreditationImpact.NONE
