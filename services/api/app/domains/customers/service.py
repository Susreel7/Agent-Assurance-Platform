"""Customer business logic.

The interesting function here is ``compute_readiness``. Everything else is the
bookkeeping that makes it possible.

Readiness answers a question an organisation currently answers by finding out the hard
way, halfway through a client's security review: *of everything this client will demand,
how much can we actually evidence?* It is computable the moment a customer's frameworks
are recorded — before any agent exists, before any evidence has been collected — which
turns a discovery made under deadline pressure into a number known at onboarding.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.customers import repository as repo
from app.domains.customers.schemas import (
    AnswerMode,
    ContactOut,
    ContactUpsert,
    ControlGap,
    CriticalityTier,
    CustomerCreate,
    CustomerDetail,
    CustomerReadiness,
    CustomerSummary,
    CustomerUpdate,
    FrameworkOut,
    FrameworkRequirementCreate,
    FrameworkRequirementOut,
    FrameworkSuggestion,
    ReadinessByFramework,
    RequirementLevel,
)

# Cap the gap list so a tier-1 client with four frameworks and no mappings does not
# return a thousand-item payload. The count in ReadinessByFramework stays exact.
MAX_GAPS_RETURNED = 50


class CoverageRow(Protocol):
    """Shape of one row from ``repository.fetch_control_coverage``.

    Declared structurally so the bucketing function can be exercised with plain
    objects, rather than only against a live query result.
    """

    framework_id: UUID
    framework_slug: str
    framework_name: str
    level: str
    control_ref: str
    title: str
    answer_mode: str
    mapping_count: int
    full_count: int


# ----------------------------------------------------------------------
# Domain exceptions. Translated to HTTP in router.py, never raised from there.
# ----------------------------------------------------------------------


class CustomerError(Exception):
    """Base for everything this module raises."""


class CustomerNotFoundError(CustomerError):
    def __init__(self, customer_id: UUID) -> None:
        super().__init__(f"customer {customer_id} not found")
        self.customer_id = customer_id


class CustomerSlugTakenError(CustomerError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"slug {slug!r} is already used in this organisation")
        self.slug = slug


class FrameworkNotFoundError(CustomerError):
    def __init__(self, framework_id: UUID) -> None:
        super().__init__(f"framework {framework_id} not found or not visible")
        self.framework_id = framework_id


class FrameworkAlreadyRequiredError(CustomerError):
    def __init__(self, framework_id: UUID) -> None:
        super().__init__(f"framework {framework_id} is already required by this customer")
        self.framework_id = framework_id


# ----------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------


async def create_customer(
    session: AsyncSession, org_id: UUID, payload: CustomerCreate
) -> CustomerDetail:
    if await repo.get_customer_by_slug(session, org_id, payload.slug):
        raise CustomerSlugTakenError(payload.slug)

    values = payload.model_dump(exclude_none=True)
    # A display name is almost always the legal name minus its corporate suffix, but
    # guessing that badly is worse than repeating it. Default to the legal name.
    values.setdefault("display_name", payload.legal_name)
    values.setdefault("operating_jurisdictions", [])

    # An operating jurisdiction list that omits the home country is nearly always an
    # oversight, and residency evaluation would silently inherit the omission.
    if payload.home_jurisdiction:
        jurisdictions = list(values["operating_jurisdictions"])
        if payload.home_jurisdiction not in jurisdictions:
            jurisdictions.insert(0, payload.home_jurisdiction)
        values["operating_jurisdictions"] = jurisdictions

    customer = await repo.insert_customer(session, org_id, values)
    return await _build_detail(session, org_id, customer.id)


async def update_customer(
    session: AsyncSession, org_id: UUID, customer_id: UUID, payload: CustomerUpdate
) -> CustomerDetail:
    if not await repo.get_customer(session, org_id, customer_id):
        raise CustomerNotFoundError(customer_id)

    values = payload.model_dump(exclude_unset=True)
    await repo.update_customer(session, org_id, customer_id, values)
    return await _build_detail(session, org_id, customer_id)


async def get_customer_detail(
    session: AsyncSession, org_id: UUID, customer_id: UUID
) -> CustomerDetail:
    if not await repo.get_customer(session, org_id, customer_id):
        raise CustomerNotFoundError(customer_id)
    return await _build_detail(session, org_id, customer_id)


async def list_customers(
    session: AsyncSession,
    org_id: UUID,
    *,
    statuses: list[str] | None = None,
    sectors: list[str] | None = None,
    criticalities: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CustomerSummary], int]:
    rows = await repo.list_customers(
        session,
        org_id,
        statuses=statuses,
        sectors=sectors,
        criticalities=criticalities,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = await repo.count_customers(
        session,
        org_id,
        statuses=statuses,
        sectors=sectors,
        criticalities=criticalities,
        search=search,
    )

    rollups = await repo.fetch_rollups(session, org_id, [r.id for r in rows])
    summaries = [
        CustomerSummary.model_validate(row).model_copy(update=rollups.get(row.id, {}))
        for row in rows
    ]
    return summaries, total


async def _build_detail(session: AsyncSession, org_id: UUID, customer_id: UUID) -> CustomerDetail:
    customer = await repo.get_customer(session, org_id, customer_id)
    if customer is None:
        raise CustomerNotFoundError(customer_id)

    contacts = await repo.list_current_contacts(session, org_id, customer_id)
    requirements = await repo.list_requirements(session, org_id, customer_id)
    rollups = await repo.fetch_rollups(session, org_id, [customer_id])

    detail = CustomerDetail.model_validate(customer)
    return detail.model_copy(
        update={
            **rollups.get(customer_id, {}),
            "contacts": [ContactOut.model_validate(c) for c in contacts],
            "frameworks": [
                FrameworkRequirementOut(
                    id=cf.id,
                    framework=_framework_out(fw, count),
                    level=RequirementLevel(cf.level),
                    scoped_controls=list(cf.scoped_controls),
                    required_since=cf.required_since,
                    notes=cf.notes,
                )
                for cf, fw, count in requirements
            ],
        }
    )


def _framework_out(framework: object, control_count: int) -> FrameworkOut:
    return FrameworkOut(
        id=framework.id,  # type: ignore[attr-defined]
        slug=framework.slug,  # type: ignore[attr-defined]
        name=framework.name,  # type: ignore[attr-defined]
        kind=framework.kind,  # type: ignore[attr-defined]
        publisher=framework.publisher,  # type: ignore[attr-defined]
        version=framework.version,  # type: ignore[attr-defined]
        is_builtin=framework.org_id is None,  # type: ignore[attr-defined]
        control_count=control_count,
    )


# ----------------------------------------------------------------------
# Contacts
# ----------------------------------------------------------------------


async def set_contact(
    session: AsyncSession, org_id: UUID, customer_id: UUID, payload: ContactUpsert
) -> ContactOut:
    """Supersede whoever currently holds this role.

    Closing the previous window rather than overwriting the row is deliberate: an
    accreditation approved last quarter must still name the person who reviewed it,
    even after they change jobs.
    """
    if not await repo.get_customer(session, org_id, customer_id):
        raise CustomerNotFoundError(customer_id)

    now = datetime.now(UTC)
    await repo.close_contact(session, org_id, customer_id, payload.role.value, now)
    contact = await repo.insert_contact(
        session,
        org_id,
        customer_id,
        {
            "role": payload.role.value,
            "principal_id": payload.principal_id,
            "display_name": payload.display_name,
            "valid_from": now,
        },
    )
    return ContactOut.model_validate(contact)


async def end_contact(session: AsyncSession, org_id: UUID, customer_id: UUID, role: str) -> None:
    if not await repo.get_customer(session, org_id, customer_id):
        raise CustomerNotFoundError(customer_id)
    await repo.close_contact(session, org_id, customer_id, role, datetime.now(UTC))


# ----------------------------------------------------------------------
# Framework requirements
# ----------------------------------------------------------------------


async def require_framework(
    session: AsyncSession,
    org_id: UUID,
    customer_id: UUID,
    payload: FrameworkRequirementCreate,
) -> FrameworkRequirementOut:
    if not await repo.get_customer(session, org_id, customer_id):
        raise CustomerNotFoundError(customer_id)

    framework = await repo.get_framework(session, org_id, payload.framework_id)
    if framework is None:
        raise FrameworkNotFoundError(payload.framework_id)

    if await repo.requirement_exists(session, org_id, customer_id, payload.framework_id):
        raise FrameworkAlreadyRequiredError(payload.framework_id)

    requirement = await repo.insert_requirement(
        session,
        org_id,
        customer_id,
        {
            "framework_id": payload.framework_id,
            "level": payload.level.value,
            "scoped_controls": payload.scoped_controls,
            "required_since": payload.required_since,
            "notes": payload.notes,
        },
    )
    counts = await repo.fetch_framework_control_counts(session, [payload.framework_id])
    return FrameworkRequirementOut(
        id=requirement.id,
        framework=_framework_out(framework, counts.get(payload.framework_id, 0)),
        level=payload.level,
        scoped_controls=payload.scoped_controls,
        required_since=payload.required_since,
        notes=payload.notes,
    )


async def drop_framework(
    session: AsyncSession, org_id: UUID, customer_id: UUID, framework_id: UUID
) -> None:
    if not await repo.get_customer(session, org_id, customer_id):
        raise CustomerNotFoundError(customer_id)
    removed = await repo.delete_requirement(session, org_id, customer_id, framework_id)
    if removed == 0:
        raise FrameworkNotFoundError(framework_id)


async def suggest_frameworks(
    session: AsyncSession,
    org_id: UUID,
    *,
    sector: str | None = None,
    jurisdiction: str | None = None,
    criticality: CriticalityTier = CriticalityTier.TIER_2,
) -> list[FrameworkSuggestion]:
    """Propose a framework set from sector and jurisdiction.

    Nobody onboarding a client wants to choose from an unordered list of standards, and
    the wrong choice is discovered late. Sector and jurisdiction narrow it to two or
    three with a stated reason, which is also a reason the operator can disagree with.
    """
    candidates = await repo.list_frameworks(session, org_id)

    suggestions: list[FrameworkSuggestion] = []
    for framework, control_count in candidates:
        sector_match = bool(sector and sector in (framework.typical_sectors or []))
        jurisdictions = framework.jurisdictions or []
        jurisdiction_match = bool(jurisdiction and jurisdiction in jurisdictions)
        universal = len(jurisdictions) == 0

        if not (sector_match or jurisdiction_match):
            continue

        if sector_match and jurisdiction_match:
            confidence, reason = (
                "strong",
                (f"Commonly required in {sector} and applies in {jurisdiction}"),
            )
        elif jurisdiction_match:
            confidence, reason = "strong", f"Applies to organisations operating in {jurisdiction}"
        elif universal:
            confidence, reason = "strong", f"Commonly required in {sector}"
        else:
            confidence, reason = "moderate", f"Often requested in {sector}"

        # A tier-1 client's reviewers escalate anything arguable, so a moderate
        # suggestion is worth surfacing as strong rather than leaving to be discovered.
        if criticality is CriticalityTier.TIER_1 and confidence == "moderate":
            confidence = "strong"
            reason += " — raised because this client is tier 1"

        suggestions.append(
            FrameworkSuggestion(
                framework=_framework_out(framework, control_count),
                reason=reason,
                confidence=confidence,
            )
        )

    suggestions.sort(key=lambda s: (s.confidence != "strong", s.framework.name))
    return suggestions


# ----------------------------------------------------------------------
# Readiness
# ----------------------------------------------------------------------


@dataclass(slots=True)
class CoverageBucket:
    """Per-framework accumulator. Separate from the response model so the counting can
    be tested without a database or a framework record."""

    framework_id: UUID
    framework_slug: str
    framework_name: str
    level: str

    in_scope: int = 0
    answerable: int = 0
    partial: int = 0
    narrative_only: int = 0
    unmapped: int = 0
    not_applicable: int = 0


def bucket_coverage(
    rows: Iterable[CoverageRow],
) -> tuple[dict[UUID, CoverageBucket], list[ControlGap]]:
    """Sort every demanded control into exactly one bucket.

    - ``narrative_only`` — answerable only by a written statement, never by evidence.
      Not a gap; it is work for a human and always will be.
    - ``answerable`` — at least one control mapping exists. ``partial`` is the subset
      where no mapping claims full satisfaction, which a reviewer will probe.
    - ``unmapped`` — nothing in the platform answers it. The real gap, and the only
      bucket that represents missing capability.
    - ``not_applicable`` — counts towards scope but towards no coverage figure, so a
      client who scoped a control out does not depress the percentage.

    Pure, so the bucketing rules are testable on their own. Getting these boundaries
    wrong would misreport readiness, and a wrong number here is worse than no number:
    it would be quoted in a client conversation.
    """
    buckets: dict[UUID, CoverageBucket] = {}
    gaps: list[ControlGap] = []

    for row in rows:
        bucket = buckets.get(row.framework_id)
        if bucket is None:
            bucket = CoverageBucket(
                framework_id=row.framework_id,
                framework_slug=row.framework_slug,
                framework_name=row.framework_name,
                level=str(row.level),
            )
            buckets[row.framework_id] = bucket

        bucket.in_scope += 1
        mode = AnswerMode(row.answer_mode)

        if mode is AnswerMode.NOT_APPLICABLE:
            bucket.not_applicable += 1
            continue

        if mode is AnswerMode.NARRATIVE:
            bucket.narrative_only += 1
            continue

        if row.mapping_count > 0:
            bucket.answerable += 1
            if row.full_count == 0:
                bucket.partial += 1
            continue

        bucket.unmapped += 1
        gaps.append(
            ControlGap(
                framework_slug=row.framework_slug,
                framework_name=row.framework_name,
                control_ref=row.control_ref,
                title=row.title,
                answer_mode=mode,
                reason="No evidence kind is mapped to this control yet",
            )
        )

    return buckets, gaps


async def compute_readiness(
    session: AsyncSession, org_id: UUID, customer_id: UUID
) -> CustomerReadiness:
    """How much of what this client demands can the platform actually evidence?

    Computable before any agent is registered, which is the point: it turns a discovery
    normally made under review deadline pressure into a number known at onboarding.
    """
    customer = await repo.get_customer(session, org_id, customer_id)
    if customer is None:
        raise CustomerNotFoundError(customer_id)

    rows = await repo.fetch_control_coverage(session, org_id, customer_id)
    buckets, gaps = bucket_coverage(rows)

    counts = await repo.fetch_framework_control_counts(session, list(buckets))
    frameworks_by_id = {
        fw.id: fw for fw, _ in await repo.list_frameworks(session, org_id) if fw.id in buckets
    }

    readiness = [
        ReadinessByFramework(
            framework=_framework_out(frameworks_by_id[framework_id], counts.get(framework_id, 0)),
            level=RequirementLevel(bucket.level),
            controls_in_scope=bucket.in_scope,
            answerable=bucket.answerable,
            partial=bucket.partial,
            narrative_only=bucket.narrative_only,
            unmapped=bucket.unmapped,
        )
        for framework_id, bucket in buckets.items()
        if framework_id in frameworks_by_id
    ]

    # Mandatory frameworks first, then widest gap. That ordering is the work queue.
    readiness.sort(key=lambda r: (r.level is not RequirementLevel.MANDATORY, -r.unmapped))

    return CustomerReadiness(
        customer_id=customer_id,
        customer_display_name=customer.display_name,
        frameworks=readiness,
        gaps=gaps[:MAX_GAPS_RETURNED],
    )
