"""Engagement drift tests.

Drift is the gap between the agent version a client approved and the one they are being
served. It is the number the product leads with, so the severity ladder needs pinning:
an operator who is shown "critical" will stop a rollout, and one who is shown
"informational" will not.

``classify_drift`` and ``_versions_behind`` are pure, so all of this runs without a
database.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.domains.engagements.schemas import DriftSeverity, VersionUptake
from app.domains.engagements.service import DriftFacts, _versions_behind, classify_drift

V1, V2, V3 = uuid4(), uuid4(), uuid4()
SEQUENCE = [V1, V2, V3]


def facts(**overrides: object) -> DriftFacts:
    base: dict[str, object] = {
        "accredited_version_id": V1,
        "deployed_version_id": V1,
        "uptake": VersionUptake.PINNED,
        "versions_behind": 0,
        "customer_criticality": "tier_2",
    }
    base.update(overrides)
    return DriftFacts(**base)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# The clean cases — a green row must be reachable
# ----------------------------------------------------------------------


def test_matching_versions_are_not_drift() -> None:
    severity, reason = classify_drift(facts())
    assert severity is DriftSeverity.NONE
    assert "matches" in reason


def test_nothing_deployed_yet_is_not_drift() -> None:
    """A scoped agent awaiting its first deployment is a plan, not an exposure.
    Reporting it as drift would bury the real cases under onboarding noise."""
    severity, _ = classify_drift(facts(deployed_version_id=None, accredited_version_id=None))
    assert severity is DriftSeverity.NONE

    severity, _ = classify_drift(facts(deployed_version_id=None))
    assert severity is DriftSeverity.NONE


# ----------------------------------------------------------------------
# Critical — stop the rollout
# ----------------------------------------------------------------------


def test_deployed_with_no_accreditation_at_all_is_critical() -> None:
    """The worst case in the product: something is serving a client and no review has
    ever happened. Worse than a stale approval, and must outrank it."""
    severity, reason = classify_drift(facts(accredited_version_id=None, deployed_version_id=V2))
    assert severity is DriftSeverity.CRITICAL
    assert "without any accredited version" in reason


def test_a_pinned_client_on_a_different_version_is_critical() -> None:
    """Pinned means the client explicitly refused automatic uptake, so this is a broken
    commitment rather than a drift of degree."""
    severity, reason = classify_drift(
        facts(deployed_version_id=V3, uptake=VersionUptake.PINNED, versions_behind=2)
    )
    assert severity is DriftSeverity.CRITICAL
    assert "pinned" in reason


def test_tier_1_escalates_material_to_critical() -> None:
    """A tier-1 client's reviewers escalate anything arguable. The platform should have
    flagged it before they did."""
    shared = {"deployed_version_id": V2, "uptake": VersionUptake.AUTO_MINOR}

    tier_2, _ = classify_drift(facts(**shared, customer_criticality="tier_2"))
    tier_1, reason = classify_drift(facts(**shared, customer_criticality="tier_1"))

    assert tier_2 is DriftSeverity.MATERIAL
    assert tier_1 is DriftSeverity.CRITICAL
    assert "tier 1" in reason


# ----------------------------------------------------------------------
# Informational — consented, but still visible
# ----------------------------------------------------------------------


def test_auto_uptake_running_ahead_is_only_informational() -> None:
    """The client agreed to this in advance. Treating it as a breach would make the
    report unreadable for anyone who offers automatic updates."""
    severity, reason = classify_drift(
        facts(deployed_version_id=V2, uptake=VersionUptake.AUTO_MINOR, versions_behind=1)
    )
    assert severity is DriftSeverity.INFORMATIONAL
    assert "auto_minor" in reason


@pytest.mark.parametrize(
    "uptake",
    [VersionUptake.AUTO_PATCH, VersionUptake.AUTO_MINOR, VersionUptake.AUTO_ALL],
)
def test_every_auto_uptake_mode_reports_ahead_as_informational(uptake: VersionUptake) -> None:
    severity, _ = classify_drift(facts(deployed_version_id=V2, uptake=uptake, versions_behind=1))
    assert severity is DriftSeverity.INFORMATIONAL


def test_informational_is_still_reported_not_suppressed() -> None:
    """Consented is not the same as "nobody should look at it". The severity exists so
    the row can be de-emphasised, not dropped."""
    severity, _ = classify_drift(
        facts(deployed_version_id=V2, uptake=VersionUptake.AUTO_ALL, versions_behind=1)
    )
    assert severity is not DriftSeverity.NONE


# ----------------------------------------------------------------------
# Material — the rollback-or-review case
# ----------------------------------------------------------------------


def test_a_rollback_under_auto_uptake_is_material_not_informational() -> None:
    """Serving something *older* than the client approved is a different problem from
    running ahead, and an uptake setting does not authorise it."""
    severity, reason = classify_drift(
        facts(
            accredited_version_id=V3,
            deployed_version_id=V1,
            uptake=VersionUptake.AUTO_ALL,
            versions_behind=0,
        )
    )
    assert severity is DriftSeverity.MATERIAL
    assert "does not cover" in reason


# ----------------------------------------------------------------------
# Distance
# ----------------------------------------------------------------------


def test_versions_behind_counts_forward_distance() -> None:
    assert _versions_behind(SEQUENCE, V1, V3) == 2
    assert _versions_behind(SEQUENCE, V1, V2) == 1
    assert _versions_behind(SEQUENCE, V2, V2) == 0


def test_a_rollback_reports_zero_rather_than_a_negative_distance() -> None:
    """ "Minus two versions ahead" is not a sentence anyone should read in a client
    report. The rollback is described by the severity and reason instead."""
    assert _versions_behind(SEQUENCE, V3, V1) == 0


def test_unknown_versions_yield_no_distance() -> None:
    """A version id absent from the sequence — deleted, or from another agent — must not
    raise inside the estate sweep."""
    assert _versions_behind(SEQUENCE, V1, uuid4()) == 0
    assert _versions_behind(SEQUENCE, uuid4(), V1) == 0
    assert _versions_behind([], V1, V2) == 0
    assert _versions_behind(SEQUENCE, None, V2) == 0
    assert _versions_behind(SEQUENCE, V1, None) == 0


# ----------------------------------------------------------------------
# Totality
# ----------------------------------------------------------------------


@pytest.mark.parametrize("uptake", list(VersionUptake))
@pytest.mark.parametrize(
    ("accredited", "deployed"),
    [(None, None), (None, V1), (V1, None), (V1, V1), (V1, V2), (V3, V1)],
)
def test_every_combination_is_ruled_with_a_reason(
    uptake: VersionUptake, accredited: UUID | None, deployed: UUID | None
) -> None:
    """No state may go unclassified, and no verdict may arrive without a sentence: the
    reason is what an operator reads in the console and forwards to the client."""
    severity, reason = classify_drift(
        facts(accredited_version_id=accredited, deployed_version_id=deployed, uptake=uptake)
    )
    assert severity in set(DriftSeverity)
    assert reason.strip()
