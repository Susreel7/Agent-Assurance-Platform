"""Policy HTTP handlers. Thin by rule — every one delegates immediately."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.policy import service
from app.domains.policy.schemas import (
    DecisionOutcome,
    EvaluationRequest,
    EvaluationResult,
    PolicyDecisionOut,
    PolicyDomain,
    PolicyPublish,
    PolicySummary,
    PolicyVersionOut,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.PolicyNotFoundError: status.HTTP_404_NOT_FOUND,
    service.PolicyVersionError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _http(exc: service.PolicyError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


class PolicyCreate(BaseModel):
    slug: str
    name: str
    description: str | None = None
    domain: PolicyDomain


class DecisionPage(BaseModel):
    items: list[PolicyDecisionOut]
    total: int
    limit: int
    offset: int


@router.get("", response_model=list[PolicySummary], summary="List policies")
async def list_policies(session: Session, org_id: VerifiedOrg) -> list[PolicySummary]:
    return await service.list_policies(session, org_id)


@router.post(
    "",
    response_model=PolicySummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a policy container",
)
async def create_policy(
    payload: PolicyCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> PolicySummary:
    return await service.create_policy(
        session,
        org_id,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        domain=payload.domain,
    )


@router.get(
    "/{policy_id}/versions",
    response_model=list[PolicyVersionOut],
    summary="List signed policy versions",
)
async def list_versions(
    policy_id: UUID, session: Session, org_id: VerifiedOrg
) -> list[PolicyVersionOut]:
    try:
        return await service.get_policy_versions(session, org_id, policy_id)
    except service.PolicyError as exc:
        raise _http(exc) from exc


@router.post(
    "/{policy_id}/versions",
    response_model=PolicyVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Publish and sign a new policy version",
)
async def publish_version(
    policy_id: UUID,
    payload: PolicyPublish,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> PolicyVersionOut:
    try:
        return await service.publish_version(session, org_id, policy_id, payload)
    except service.PolicyError as exc:
        raise _http(exc) from exc


@router.post("/-/evaluate", response_model=EvaluationResult, summary="Evaluate a request")
async def evaluate_policy(
    payload: EvaluationRequest,
    session: Session,
    org_id: VerifiedOrg,
    policy_id: Annotated[UUID, Query()],
) -> EvaluationResult:
    try:
        return await service.evaluate(session, org_id, policy_id, payload)
    except service.PolicyError as exc:
        raise _http(exc) from exc


@router.get("/-/decisions", response_model=DecisionPage, summary="List policy decisions")
async def list_decisions(
    session: Session,
    org_id: VerifiedOrg,
    outcome: Annotated[list[DecisionOutcome] | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DecisionPage:
    outcomes = [o.value for o in outcome] if outcome else None
    items, total = await service.list_policy_decisions(
        session, org_id, outcomes=outcomes, agent_id=agent_id, limit=limit, offset=offset
    )
    return DecisionPage(items=items, total=total, limit=limit, offset=offset)
