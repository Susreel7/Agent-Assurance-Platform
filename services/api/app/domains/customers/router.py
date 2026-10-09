"""Customer HTTP handlers. Thin by rule — every one delegates immediately.

Domain exceptions are translated here and nowhere else, which is why the mapping is a
single dictionary rather than try/except blocks scattered through the handlers.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.api.deps import Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.customers import service
from app.domains.customers.schemas import (
    ContactOut,
    ContactRole,
    ContactUpsert,
    CriticalityTier,
    CustomerCreate,
    CustomerDetail,
    CustomerReadiness,
    CustomerStatus,
    CustomerSummary,
    CustomerUpdate,
    FrameworkRequirementCreate,
    FrameworkRequirementOut,
    FrameworkSuggestion,
    Sector,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.CustomerNotFoundError: status.HTTP_404_NOT_FOUND,
    service.FrameworkNotFoundError: status.HTTP_404_NOT_FOUND,
    service.CustomerSlugTakenError: status.HTTP_409_CONFLICT,
    service.FrameworkAlreadyRequiredError: status.HTTP_409_CONFLICT,
}


def _http(exc: service.CustomerError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


class CustomerPage(BaseModel):
    items: list[CustomerSummary]
    total: int
    limit: int
    offset: int


class ReadinessResponse(BaseModel):
    """Wraps the model so the computed properties cross the wire.

    Pydantic does not serialise ``@property``, and a client that has to recompute
    coverage will eventually compute it differently from the console.
    """

    readiness: CustomerReadiness
    headline: str
    total_controls: int
    total_answerable: int
    coverage_pct: float


# ----------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------


@router.post(
    "",
    response_model=CustomerDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Register a client whose approval is required",
)
async def create_customer(
    payload: CustomerCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> CustomerDetail:
    try:
        return await service.create_customer(session, org_id, payload)
    except service.CustomerError as exc:
        raise _http(exc) from exc


@router.get("", response_model=CustomerPage, summary="List clients")
async def list_customers(
    session: Session,
    org_id: VerifiedOrg,
    status_filter: Annotated[list[CustomerStatus] | None, Query(alias="status")] = None,
    sector: Annotated[list[Sector] | None, Query()] = None,
    criticality: Annotated[list[CriticalityTier] | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerPage:
    items, total = await service.list_customers(
        session,
        org_id,
        statuses=[s.value for s in status_filter] if status_filter else None,
        sectors=[s.value for s in sector] if sector else None,
        criticalities=[c.value for c in criticality] if criticality else None,
        search=search,
        limit=limit,
        offset=offset,
    )
    return CustomerPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{customer_id}", response_model=CustomerDetail, summary="Get one client")
async def get_customer(customer_id: UUID, session: Session, org_id: VerifiedOrg) -> CustomerDetail:
    try:
        return await service.get_customer_detail(session, org_id, customer_id)
    except service.CustomerError as exc:
        raise _http(exc) from exc


@router.patch("/{customer_id}", response_model=CustomerDetail, summary="Update a client")
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> CustomerDetail:
    try:
        return await service.update_customer(session, org_id, customer_id, payload)
    except service.CustomerError as exc:
        raise _http(exc) from exc


# No DELETE. A client whose review produced an accreditation cannot be erased without
# orphaning that evidence; set status to 'churned' instead.


# ----------------------------------------------------------------------
# Contacts
# ----------------------------------------------------------------------


@router.put(
    "/{customer_id}/contacts",
    response_model=ContactOut,
    summary="Set the holder of a contact role, superseding the previous one",
)
async def set_contact(
    customer_id: UUID,
    payload: ContactUpsert,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ContactOut:
    try:
        return await service.set_contact(session, org_id, customer_id, payload)
    except service.CustomerError as exc:
        raise _http(exc) from exc


@router.delete(
    "/{customer_id}/contacts/{role}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End a contact role's validity window",
)
async def end_contact(
    customer_id: UUID,
    role: ContactRole,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> Response:
    try:
        await service.end_contact(session, org_id, customer_id, role.value)
    except service.CustomerError as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------
# Framework requirements
# ----------------------------------------------------------------------


@router.post(
    "/{customer_id}/frameworks",
    response_model=FrameworkRequirementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a framework this client demands",
)
async def require_framework(
    customer_id: UUID,
    payload: FrameworkRequirementCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> FrameworkRequirementOut:
    try:
        return await service.require_framework(session, org_id, customer_id, payload)
    except service.CustomerError as exc:
        raise _http(exc) from exc


@router.delete(
    "/{customer_id}/frameworks/{framework_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop requiring a framework for this client",
)
async def drop_framework(
    customer_id: UUID,
    framework_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> Response:
    try:
        await service.drop_framework(session, org_id, customer_id, framework_id)
    except service.CustomerError as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/-/framework-suggestions",
    response_model=list[FrameworkSuggestion],
    summary="Suggest frameworks from sector and jurisdiction",
)
async def suggest_frameworks(
    session: Session,
    org_id: VerifiedOrg,
    sector: Annotated[Sector | None, Query()] = None,
    jurisdiction: Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")] = None,
    criticality: Annotated[CriticalityTier, Query()] = CriticalityTier.TIER_2,
) -> list[FrameworkSuggestion]:
    """Path is ``/-/`` so it cannot collide with a customer UUID."""
    return await service.suggest_frameworks(
        session,
        org_id,
        sector=sector.value if sector else None,
        jurisdiction=jurisdiction,
        criticality=criticality,
    )


# ----------------------------------------------------------------------
# Readiness
# ----------------------------------------------------------------------


@router.get(
    "/{customer_id}/readiness",
    response_model=ReadinessResponse,
    summary="How much of what this client demands can we evidence?",
)
async def get_readiness(
    customer_id: UUID, session: Session, org_id: VerifiedOrg
) -> ReadinessResponse:
    try:
        readiness = await service.compute_readiness(session, org_id, customer_id)
    except service.CustomerError as exc:
        raise _http(exc) from exc

    return ReadinessResponse(
        readiness=readiness,
        headline=readiness.headline(),
        total_controls=readiness.total_controls,
        total_answerable=readiness.total_answerable,
        coverage_pct=readiness.coverage_pct,
    )
