"""Materiality HTTP handlers. Thin by rule."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentPrincipal, Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.materiality import service
from app.domains.materiality.schemas import (
    AdjudicationOut,
    AdjudicationRequest,
    AssessmentOut,
    ReviewQueue,
    RuleCatalogue,
    RuleOut,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.ChangeNotFoundError: status.HTTP_404_NOT_FOUND,
    service.ReleaseNotFoundError: status.HTTP_404_NOT_FOUND,
    service.UnknownRuleError: status.HTTP_404_NOT_FOUND,
    service.AlreadyAdjudicatedError: status.HTTP_409_CONFLICT,
}


def _http(exc: service.MaterialityError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


class AssessRequest(BaseModel):
    """Two descriptors, ruled without persisting anything.

    Deliberately accepts raw descriptors rather than version ids: the CI gate runs
    against a change that has not been deployed and may never be, so requiring a
    registered version would defeat the purpose.
    """

    model_config = ConfigDict(extra="forbid")

    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any]
    agent_id: UUID | None = None
    framework_slug: str | None = Field(
        default=None,
        description="Rule under a specific framework rather than the agent's strictest.",
    )


@router.post(
    "/-/assess",
    response_model=AssessmentOut,
    summary="Rule on two descriptors without persisting",
)
async def assess(
    payload: AssessRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> AssessmentOut:
    """What the CI hook calls. Writes nothing, so it is safe on every push."""
    return await service.assess_descriptors(
        session,
        org_id,
        payload.before,
        payload.after,
        agent_id=payload.agent_id,
        framework_slug=payload.framework_slug,
    )


@router.post(
    "/releases/{release_id}/assess",
    response_model=AssessmentOut,
    summary="Rule on a persisted release and record the verdicts",
)
async def assess_release(
    release_id: UUID,
    session: Session,
    _write: WriteEnabled,
    org_id: VerifiedOrg,
    framework_slug: Annotated[str | None, Query(max_length=64)] = None,
) -> AssessmentOut:
    try:
        return await service.assess_release(
            session, org_id, release_id, framework_slug=framework_slug
        )
    except service.MaterialityError as exc:
        raise _http(exc) from exc


@router.get(
    "/-/queue",
    response_model=ReviewQueue,
    summary="Changes awaiting human adjudication, ordered by consequence",
)
async def review_queue(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewQueue:
    return await service.get_review_queue(session, org_id, limit=limit, offset=offset)


@router.post(
    "/changes/{change_id}/adjudicate",
    response_model=AdjudicationOut,
    summary="Record a human ruling on a change",
)
async def adjudicate(
    change_id: UUID,
    payload: AdjudicationRequest,
    session: Session,
    _write: WriteEnabled,
    org_id: VerifiedOrg,
) -> AdjudicationOut:
    """A decision here can become a standing override, which is how the rule set is
    tuned by the customers who use it rather than only by us."""
    try:
        return await service.adjudicate(
            session,
            org_id,
            change_id,
            verdict=payload.verdict,
            reason=payload.reason,
            # Until the identity provider is wired, the acting principal is recorded
            # as the API caller rather than guessed. Tracked as Q-002.
            actor="person:api",
            apply_to_rule=payload.apply_to_rule,
        )
    except service.MaterialityError as exc:
        raise _http(exc) from exc


@router.get(
    "/-/rules",
    response_model=RuleCatalogue,
    summary="The materiality rule set and this organisation's overrides",
)
async def rules(session: Session, org_id: VerifiedOrg) -> RuleCatalogue:
    return await service.get_rule_catalogue(session, org_id)


@router.get(
    "/-/rules/{rule_id}",
    response_model=RuleOut,
    summary="Explain one rule by id",
)
async def rule(rule_id: str, _: CurrentPrincipal) -> RuleOut:
    """Resolves a stored verdict's rule id to its current text, which is how a release
    ruled under an earlier rule set stays explainable.

    Authenticated but not tenant-scoped, unlike the catalogue above: rule text is the
    same for every organisation, so there is nothing here to scope. It still needs a
    caller, because without one the rule set was readable by anyone who could reach the
    API — it was the only `/v1` route with no dependency at all.
    """
    try:
        return service.explain(rule_id)
    except service.MaterialityError as exc:
        raise _http(exc) from exc
