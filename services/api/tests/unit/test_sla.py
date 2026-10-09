"""Unit tests for SLO pure logic."""

from __future__ import annotations

from decimal import Decimal

from app.domains.sla.service import (
    compute_service_credit_amount,
    select_worst_credit_tier,
    weighted_attainment,
)


def test_weighted_attainment_not_plain_mean() -> None:
    buckets = [(Decimal("100"), 3), (Decimal("50"), 1_000_000)]
    att = weighted_attainment(buckets)
    assert att is not None
    assert att > Decimal("50.0000")
    assert att < Decimal("100")


def test_weighted_attainment_empty() -> None:
    assert weighted_attainment([]) is None


def test_credit_tier_picks_worst_breached() -> None:
    model = {
        "basis": "percentage_of_monthly_fee",
        "tiers": [{"below": 99.9, "credit_pct": 5}, {"below": 99.0, "credit_pct": 15}],
    }
    pct, basis = select_worst_credit_tier(model, Decimal("98.5"))
    assert pct == Decimal("15")
    assert basis == "percentage_of_monthly_fee"


def test_no_credit_when_attainment_meets_target() -> None:
    model = {"tiers": [{"below": 99.9, "credit_pct": 5}]}
    pct, _ = select_worst_credit_tier(model, Decimal("99.95"))
    assert pct is None


def test_compute_service_credit_gbp() -> None:
    model = {
        "basis": "percentage_of_monthly_fee",
        "tiers": [{"below": 99.9, "credit_pct": 5}],
    }
    amount, basis = compute_service_credit_amount(model, Decimal("99.0"), Decimal("10000"))
    assert amount == Decimal("500.00")
    assert basis == "percentage_of_monthly_fee"
