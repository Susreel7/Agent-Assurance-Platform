"""Service level measurements, attainment and contractual credits.

Attainment is sample-weighted because a bucket with three requests must not count as
much as one with three million — a plain mean of bucket values would lie to customers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sla import repository as repo
from app.domains.sla.schemas import (
    BreachOut,
    EngagementSloSummary,
    EngagementSummaryOut,
    MeasurementCreate,
    MeasurementOut,
    SloCreate,
    SloOut,
)

_QUANT = Decimal("0.0001")


class SloError(Exception):
    """Base for everything this module raises."""


class SloNotFoundError(SloError):
    def __init__(self, slo_id: UUID) -> None:
        super().__init__(f"SLO {slo_id} not found")
        self.slo_id = slo_id


class EngagementNotFoundError(SloError):
    def __init__(self, engagement_id: UUID) -> None:
        super().__init__(f"engagement {engagement_id} not found")
        self.engagement_id = engagement_id


def weighted_attainment(buckets: list[tuple[Decimal, int]]) -> Decimal | None:
    """Sample-weighted mean of bucket values, or None when there is no data."""
    total_samples = sum(sample for _, sample in buckets)
    if total_samples <= 0:
        return None
    weighted = sum(value * Decimal(sample) for value, sample in buckets)
    return (weighted / Decimal(total_samples)).quantize(_QUANT)


def select_worst_credit_tier(
    penalty_model: dict[str, Any],
    attainment: Decimal,
) -> tuple[Decimal | None, str | None]:
    """Pick the worst tier breached — lower attainment means a higher credit."""
    tiers = penalty_model.get("tiers") or []
    if not isinstance(tiers, list):
        return None, None
    basis = str(penalty_model.get("basis", "percentage_of_monthly_fee"))
    applicable: list[tuple[Decimal, Decimal]] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        below = tier.get("below")
        credit_pct = tier.get("credit_pct")
        if below is None or credit_pct is None:
            continue
        threshold = Decimal(str(below))
        if attainment < threshold:
            applicable.append((threshold, Decimal(str(credit_pct))))
    if not applicable:
        return None, None
    applicable.sort(key=lambda pair: pair[0])
    worst_pct = applicable[0][1]
    return worst_pct, basis


def compute_service_credit_amount(
    penalty_model: dict[str, Any],
    attainment: Decimal,
    monthly_fee_gbp: Decimal = Decimal("10000"),
) -> tuple[Decimal | None, str | None]:
    """Convert the breached tier into a GBP amount for the breach row."""
    pct, basis = select_worst_credit_tier(penalty_model, attainment)
    if pct is None:
        return None, None
    if basis == "percentage_of_monthly_fee":
        amount = (monthly_fee_gbp * pct / Decimal(100)).quantize(Decimal("0.01"))
        return amount, basis
    return pct.quantize(Decimal("0.01")), basis


def _window_start(window: str, now: datetime) -> datetime:
    if window == "hourly":
        return now - timedelta(hours=1)
    if window == "daily":
        return now - timedelta(days=1)
    if window == "weekly":
        return now - timedelta(days=7)
    if window == "quarterly":
        return now - timedelta(days=90)
    return now - timedelta(days=30)


async def define_slo(session: AsyncSession, org_id: UUID, payload: SloCreate) -> SloOut:
    if payload.engagement_id is None and payload.agent_id is None:
        raise SloError("engagement_id or agent_id is required")
    row = await repo.insert_slo_definition(
        session,
        org_id,
        {
            "id": uuid4(),
            "engagement_id": payload.engagement_id,
            "agent_id": payload.agent_id,
            "service_level_id": payload.service_level_id,
            "kind": payload.kind.value,
            "target": payload.target,
            "unit": payload.unit,
            "measurement_window": payload.measurement_window,
            "penalty_model": payload.penalty_model,
            "is_enabled": True,
            "created_at": datetime.now(tz=UTC),
        },
    )
    return SloOut.model_validate(row)


async def get_slo(session: AsyncSession, org_id: UUID, slo_id: UUID) -> SloOut:
    row = await repo.get_slo_definition(session, org_id, slo_id)
    if row is None:
        raise SloNotFoundError(slo_id)
    return SloOut.model_validate(row)


async def list_slos(
    session: AsyncSession,
    org_id: UUID,
    engagement_id: UUID | None = None,
) -> list[SloOut]:
    rows = await repo.list_slo_definitions(session, org_id, engagement_id=engagement_id)
    return [SloOut.model_validate(r) for r in rows]


async def record_measurement(
    session: AsyncSession,
    org_id: UUID,
    slo_id: UUID,
    payload: MeasurementCreate,
) -> MeasurementOut:
    slo = await repo.get_slo_definition(session, org_id, slo_id)
    if slo is None:
        raise SloNotFoundError(slo_id)
    breaching = payload.value < slo.target
    existing = await repo.get_measurement_for_bucket(session, org_id, slo_id, payload.bucket_start)
    if existing is not None:
        row = await repo.update_measurement(
            session,
            org_id,
            existing.id,
            {
                "value": payload.value,
                "sample_count": payload.sample_count,
                "is_breaching": breaching,
                "computed_at": datetime.now(tz=UTC),
            },
        )
        assert row is not None
        return MeasurementOut.model_validate(row)

    row = await repo.insert_measurement(
        session,
        org_id,
        {
            "id": uuid4(),
            "slo_id": slo_id,
            "bucket_start": payload.bucket_start,
            "bucket_end": payload.bucket_end,
            "value": payload.value,
            "sample_count": payload.sample_count,
            "is_breaching": breaching,
            "computed_at": datetime.now(tz=UTC),
        },
    )
    return MeasurementOut.model_validate(row)


async def compute_attainment(
    session: AsyncSession,
    org_id: UUID,
    slo_id: UUID,
    window: str | None = None,
) -> Decimal | None:
    slo = await repo.get_slo_definition(session, org_id, slo_id)
    if slo is None:
        raise SloNotFoundError(slo_id)
    win = window or slo.measurement_window
    since = _window_start(win, datetime.now(tz=UTC))
    buckets = await repo.list_measurements_since(session, org_id, slo_id, since)
    pairs = [(row.value, int(row.sample_count)) for row in buckets]
    return weighted_attainment(pairs)


async def detect_breaches(session: AsyncSession, org_id: UUID, slo_id: UUID) -> BreachOut | None:
    slo = await repo.get_slo_definition(session, org_id, slo_id)
    if slo is None:
        raise SloNotFoundError(slo_id)
    attainment = await compute_attainment(session, org_id, slo_id)
    if attainment is None:
        return None

    open_breach = await repo.get_open_breach(session, org_id, slo_id)
    if attainment < slo.target:
        if open_breach is None:
            credit, basis = compute_service_credit_amount(dict(slo.penalty_model), attainment)
            row = await repo.insert_breach(
                session,
                org_id,
                {
                    "id": uuid4(),
                    "slo_id": slo_id,
                    "started_at": datetime.now(tz=UTC),
                    "worst_value": attainment,
                    "target": slo.target,
                    "credit_amount": credit,
                    "credit_currency": "GBP",
                    "credit_basis": basis,
                },
            )
            return BreachOut.model_validate(row)
        return BreachOut.model_validate(open_breach)

    if open_breach is not None:
        closed = await repo.update_breach(
            session,
            org_id,
            open_breach.id,
            {"ended_at": datetime.now(tz=UTC)},
        )
        assert closed is not None
        return BreachOut.model_validate(closed)
    return None


async def compute_service_credit(
    session: AsyncSession,
    org_id: UUID,
    breach_id: UUID,
) -> Decimal | None:
    breach = await repo.get_breach(session, org_id, breach_id)
    if breach is None:
        raise SloError(f"breach {breach_id} not found")
    if breach.credit_amount is not None:
        return breach.credit_amount
    slo = await repo.get_slo_definition(session, org_id, breach.slo_id)
    if slo is None:
        return None
    amount, basis = compute_service_credit_amount(dict(slo.penalty_model), breach.worst_value)
    if amount is not None:
        await repo.update_breach(
            session,
            org_id,
            breach_id,
            {"credit_amount": amount, "credit_basis": basis},
        )
    return amount


async def summarise_engagement(
    session: AsyncSession,
    org_id: UUID,
    engagement_id: UUID,
) -> EngagementSummaryOut:
    if not await repo.engagement_exists(session, org_id, engagement_id):
        raise EngagementNotFoundError(engagement_id)

    slos = await repo.list_slo_definitions(session, org_id, engagement_id=engagement_id)
    summaries: list[EngagementSloSummary] = []
    total_credit = Decimal("0")

    for slo in slos:
        attainment = await compute_attainment(session, org_id, slo.id)
        open_count = await repo.count_open_breaches(session, org_id, slo.id)
        credit_sum = await repo.sum_breach_credits(session, org_id, slo.id)
        total_credit += credit_sum
        summaries.append(
            EngagementSloSummary(
                slo_id=slo.id,
                kind=slo.kind,
                target=slo.target,
                attainment=attainment,
                open_breach_count=open_count,
                total_credit_gbp=credit_sum,
            )
        )

    return EngagementSummaryOut(
        engagement_id=engagement_id,
        slos=summaries,
        total_credit_gbp=total_credit.quantize(Decimal("0.01")),
    )


async def list_breaches(
    session: AsyncSession,
    org_id: UUID,
    slo_id: UUID,
) -> list[BreachOut]:
    rows = await repo.list_breaches(session, org_id, slo_id)
    return [BreachOut.model_validate(r) for r in rows]
