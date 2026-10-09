"""Unit tests for assurance pure logic."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domains.assurance.schemas import FindingState, PostureInputs
from app.domains.assurance.service import (
    compute_posture_arithmetic,
    finding_fingerprint,
    resolution_consistent,
    score_to_band,
    simulate_probe_pass,
)


def test_fingerprint_stable_and_deduplicates_key_fields() -> None:
    agent = uuid4()
    a = finding_fingerprint("probe", "jailbreak", agent, "PI-01")
    b = finding_fingerprint("probe", "jailbreak", agent, "PI-01")
    c = finding_fingerprint("probe", "jailbreak", agent, "PI-02")
    assert a == b
    assert a != c
    assert a.startswith("sha256:")


def test_resolution_consistent_matches_database_check() -> None:
    now = datetime.now(tz=UTC)
    assert resolution_consistent(FindingState.FIXED, now)
    assert not resolution_consistent(FindingState.OPEN, now)
    assert resolution_consistent(FindingState.OPEN, None)


def test_posture_contributors_never_empty() -> None:
    score, contributors = compute_posture_arithmetic(PostureInputs())
    assert score == 100
    assert len(contributors) >= 2
    assert contributors[0].factor == "baseline"


def test_posture_arithmetic_critical_and_high() -> None:
    score, contributors = compute_posture_arithmetic(
        PostureInputs(open_critical_count=2, open_high_count=1)
    )
    assert score == 100 - 30 - 8
    factors = {c.factor for c in contributors}
    assert "open_critical_findings" in factors
    assert "open_high_findings" in factors


def test_posture_bands() -> None:
    assert score_to_band(90) == "strong"
    assert score_to_band(75) == "adequate"
    assert score_to_band(55) == "weak"
    assert score_to_band(40) == "critical"


def test_simulate_probe_deterministic() -> None:
    agent = UUID("00000000-0000-0000-0000-000000000001")
    first = simulate_probe_pass("PI-01", agent)
    second = simulate_probe_pass("PI-01", agent)
    assert first == second
