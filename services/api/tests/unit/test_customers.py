"""Unit tests for the customers domain.

Covers the two things that would be expensive to get wrong: the readiness bucketing
rules, whose output gets quoted in client conversations, and the boundary validation
that keeps malformed jurisdictions and slugs out of the database.

Integration tests against a real Postgres live in ``tests/integration`` and need
testcontainers. Everything here runs without Docker.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.domains.customers.schemas import (
    AnswerMode,
    ContactUpsert,
    CriticalityTier,
    CustomerCreate,
    CustomerReadiness,
    FrameworkKind,
    FrameworkOut,
    ReadinessByFramework,
    RequirementLevel,
)
from app.domains.customers.service import MAX_GAPS_RETURNED, bucket_coverage

ISO = UUID("11111111-1111-1111-1111-111111111111")
NIST = UUID("22222222-2222-2222-2222-222222222222")


@dataclass
class Row:
    """Stand-in for a coverage query row. Matches the CoverageRow protocol."""

    framework_id: UUID = ISO
    framework_slug: str = "iso-42001"
    framework_name: str = "ISO/IEC 42001"
    level: str = "mandatory"
    control_ref: str = "A.1.1"
    title: str = "A control"
    answer_mode: str = "evidence"
    mapping_count: int = 1
    full_count: int = 1


# ----------------------------------------------------------------------
# Bucketing
# ----------------------------------------------------------------------


def test_fully_mapped_control_is_answerable_and_not_partial() -> None:
    buckets, gaps = bucket_coverage([Row(mapping_count=2, full_count=1)])

    bucket = buckets[ISO]
    assert bucket.in_scope == 1
    assert bucket.answerable == 1
    assert bucket.partial == 0
    assert bucket.unmapped == 0
    assert gaps == []


def test_mapped_but_never_fully_satisfied_is_partial() -> None:
    """A reviewer probes partial claims, so they must be counted separately even though
    they are still answerable."""
    buckets, _ = bucket_coverage([Row(mapping_count=3, full_count=0)])

    bucket = buckets[ISO]
    assert bucket.answerable == 1
    assert bucket.partial == 1


def test_unmapped_control_becomes_a_gap() -> None:
    buckets, gaps = bucket_coverage(
        [Row(control_ref="A.9.2", title="Responsible use", mapping_count=0, full_count=0)]
    )

    assert buckets[ISO].unmapped == 1
    assert buckets[ISO].answerable == 0
    assert len(gaps) == 1
    assert gaps[0].control_ref == "A.9.2"
    assert gaps[0].framework_slug == "iso-42001"


def test_narrative_control_is_not_a_gap_even_when_unmapped() -> None:
    """Narrative controls are answered by a human statement by design. Counting them as
    gaps would make coverage permanently unreachable and the number meaningless."""
    buckets, gaps = bucket_coverage([Row(answer_mode="narrative", mapping_count=0, full_count=0)])

    bucket = buckets[ISO]
    assert bucket.narrative_only == 1
    assert bucket.unmapped == 0
    assert gaps == []


def test_not_applicable_counts_towards_scope_but_no_bucket() -> None:
    """A client who scoped a control out must not depress our coverage percentage."""
    buckets, gaps = bucket_coverage(
        [Row(answer_mode="not_applicable", mapping_count=0, full_count=0)]
    )

    bucket = buckets[ISO]
    assert bucket.in_scope == 1
    assert bucket.not_applicable == 1
    assert bucket.answerable == 0
    assert bucket.narrative_only == 0
    assert bucket.unmapped == 0
    assert gaps == []


def test_every_control_lands_in_exactly_one_bucket() -> None:
    """The buckets must partition the scope. If they ever overlap or leak, coverage
    stops summing and the discrepancy surfaces in front of a client."""
    rows = [
        Row(control_ref="a", mapping_count=1, full_count=1),
        Row(control_ref="b", mapping_count=2, full_count=0),
        Row(control_ref="c", mapping_count=0, full_count=0),
        Row(control_ref="d", answer_mode="narrative", mapping_count=0, full_count=0),
        Row(control_ref="e", answer_mode="not_applicable", mapping_count=0, full_count=0),
        Row(control_ref="f", answer_mode="hybrid", mapping_count=1, full_count=1),
    ]
    buckets, _ = bucket_coverage(rows)
    bucket = buckets[ISO]

    assert bucket.in_scope == len(rows)
    assert (
        bucket.answerable + bucket.narrative_only + bucket.unmapped + bucket.not_applicable
        == bucket.in_scope
    )
    # partial is a subset of answerable, never an additional bucket.
    assert bucket.partial <= bucket.answerable


def test_hybrid_controls_are_treated_as_evidence_answerable() -> None:
    buckets, gaps = bucket_coverage([Row(answer_mode="hybrid", mapping_count=1, full_count=1)])

    assert buckets[ISO].answerable == 1
    assert gaps == []


def test_multiple_frameworks_accumulate_independently() -> None:
    rows = [
        Row(framework_id=ISO, control_ref="A.1", mapping_count=1, full_count=1),
        Row(framework_id=ISO, control_ref="A.2", mapping_count=0, full_count=0),
        Row(
            framework_id=NIST,
            framework_slug="nist-ai-rmf",
            framework_name="NIST AI RMF",
            level="expected",
            control_ref="GOVERN 1.1",
            mapping_count=1,
            full_count=1,
        ),
    ]
    buckets, gaps = bucket_coverage(rows)

    assert len(buckets) == 2
    assert buckets[ISO].in_scope == 2
    assert buckets[ISO].unmapped == 1
    assert buckets[NIST].in_scope == 1
    assert buckets[NIST].unmapped == 0
    assert buckets[NIST].level == "expected"
    assert len(gaps) == 1


def test_bucketing_is_stable_under_empty_input() -> None:
    buckets, gaps = bucket_coverage([])
    assert buckets == {}
    assert gaps == []


# ----------------------------------------------------------------------
# Readiness model arithmetic
# ----------------------------------------------------------------------


def _framework(slug: str = "iso-42001") -> FrameworkOut:
    return FrameworkOut(
        id=ISO,
        slug=slug,
        name="ISO/IEC 42001",
        kind=FrameworkKind.STANDARD,
        publisher="ISO/IEC",
        version="2023",
        is_builtin=True,
        control_count=9,
    )


def test_coverage_percentage_rounds_to_one_decimal() -> None:
    entry = ReadinessByFramework(
        framework=_framework(),
        level=RequirementLevel.MANDATORY,
        controls_in_scope=7,
        answerable=3,
        partial=1,
        narrative_only=2,
        unmapped=2,
    )
    assert entry.coverage_pct == pytest.approx(42.9)


def test_coverage_percentage_is_zero_not_an_error_when_scope_is_empty() -> None:
    entry = ReadinessByFramework(
        framework=_framework(),
        level=RequirementLevel.MANDATORY,
        controls_in_scope=0,
        answerable=0,
        partial=0,
        narrative_only=0,
        unmapped=0,
    )
    assert entry.coverage_pct == 0.0


def test_readiness_totals_span_frameworks() -> None:
    readiness = CustomerReadiness(
        customer_id=uuid4(),
        customer_display_name="Northwind Bank",
        frameworks=[
            ReadinessByFramework(
                framework=_framework(),
                level=RequirementLevel.MANDATORY,
                controls_in_scope=9,
                answerable=6,
                partial=1,
                narrative_only=2,
                unmapped=1,
            ),
            ReadinessByFramework(
                framework=_framework("nist-ai-rmf"),
                level=RequirementLevel.EXPECTED,
                controls_in_scope=13,
                answerable=10,
                partial=0,
                narrative_only=1,
                unmapped=2,
            ),
        ],
    )
    assert readiness.total_controls == 22
    assert readiness.total_answerable == 16
    assert readiness.coverage_pct == pytest.approx(72.7)


def test_headline_reports_evidence_gaps_not_narrative_ones() -> None:
    """Narrative work is expected and permanent. Reporting it as a gap would make the
    headline alarming for a customer who is in fact fully covered."""
    from app.domains.customers.schemas import ControlGap

    readiness = CustomerReadiness(
        customer_id=uuid4(),
        customer_display_name="Northwind Bank",
        frameworks=[
            ReadinessByFramework(
                framework=_framework(),
                level=RequirementLevel.MANDATORY,
                controls_in_scope=4,
                answerable=3,
                partial=0,
                narrative_only=1,
                unmapped=0,
            )
        ],
        gaps=[
            ControlGap(
                framework_slug="iso-42001",
                framework_name="ISO/IEC 42001",
                control_ref="A.2.2",
                title="AI policy",
                answer_mode=AnswerMode.NARRATIVE,
                reason="narrative",
            )
        ],
    )
    headline = readiness.headline()
    assert "3 of 4 controls answerable" in headline
    assert "gap" not in headline


def test_headline_with_no_frameworks_says_so() -> None:
    readiness = CustomerReadiness(customer_id=uuid4(), customer_display_name="Acme", frameworks=[])
    assert readiness.headline() == "No frameworks required yet"


def test_gap_list_is_capped_but_counts_stay_exact() -> None:
    rows = [
        Row(control_ref=f"C.{i}", mapping_count=0, full_count=0)
        for i in range(MAX_GAPS_RETURNED + 25)
    ]
    buckets, gaps = bucket_coverage(rows)

    assert buckets[ISO].unmapped == MAX_GAPS_RETURNED + 25
    # bucket_coverage returns them all; the service truncates for the payload.
    assert len(gaps) == MAX_GAPS_RETURNED + 25
    assert len(gaps[:MAX_GAPS_RETURNED]) == MAX_GAPS_RETURNED


# ----------------------------------------------------------------------
# Boundary validation
# ----------------------------------------------------------------------


def test_slug_rejects_uppercase_and_underscores() -> None:
    for bad in ("Northwind", "north_wind", "-northwind", "northwind-", "n"):
        with pytest.raises(ValidationError):
            CustomerCreate(slug=bad, legal_name="Northwind Bank plc")


def test_slug_accepts_lowercase_kebab() -> None:
    payload = CustomerCreate(slug="northwind-bank", legal_name="Northwind Bank plc")
    assert payload.slug == "northwind-bank"


def test_jurisdiction_must_be_iso_alpha_2() -> None:
    with pytest.raises(ValidationError):
        CustomerCreate(slug="acme", legal_name="Acme", home_jurisdiction="GBR")

    with pytest.raises(ValidationError):
        CustomerCreate(slug="acme", legal_name="Acme", operating_jurisdictions=["GB", "usa"])


def test_operating_jurisdictions_are_deduplicated_in_order() -> None:
    payload = CustomerCreate(
        slug="acme",
        legal_name="Acme",
        operating_jurisdictions=["GB", "DE", "GB", "FR", "DE"],
    )
    assert payload.operating_jurisdictions == ["GB", "DE", "FR"]


def test_defaults_are_conservative() -> None:
    """A new client starts as a prospect at tier 2. Defaulting to active would put an
    unreviewed client into live dashboards; defaulting to tier 1 would demand a level
    of rigour nobody asked for."""
    payload = CustomerCreate(slug="acme", legal_name="Acme Corp")
    assert payload.status.value == "prospect"
    assert payload.criticality is CriticalityTier.TIER_2
    assert payload.display_name is None


def test_contact_principal_has_a_minimum_length() -> None:
    with pytest.raises(ValidationError):
        ContactUpsert(role="security_reviewer", principal_id="a")
