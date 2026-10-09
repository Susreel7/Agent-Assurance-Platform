"""Release HTTP handlers. Thin by rule — every one delegates immediately."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.releases import service
from app.domains.releases.schemas import (
    ChangeAdjudicateRequest,
    ChangeCategory,
    ReleaseCreate,
    ReleaseDetail,
    ReleaseGateVerdict,
    ReleasePage,
    ReleasePreviewRequest,
    ReleaseReviewBrief,
    ReleaseState,
    ReleaseTransitionRequest,
    SemanticChange,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.ReleaseNotFoundError: status.HTTP_404_NOT_FOUND,
    service.ChangeNotFoundError: status.HTTP_404_NOT_FOUND,
    service.InvalidTransitionError: status.HTTP_409_CONFLICT,
    service.DigestMismatchError: status.HTTP_409_CONFLICT,
    service.ReleaseValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _http(exc: service.ReleaseError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get("", response_model=ReleasePage, summary="List releases")
async def list_releases(
    session: Session,
    org_id: VerifiedOrg,
    state: Annotated[list[ReleaseState] | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
    material_only: Annotated[bool, Query()] = False,
    category: Annotated[list[ChangeCategory] | None, Query()] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReleasePage:
    cats = [c.value for c in category] if category else None
    states = [s.value for s in state] if state else None
    items, total = await service.list_releases(
        session,
        org_id,
        states=states,
        agent_id=agent_id,
        material_only=material_only,
        categories=cats,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return ReleasePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{release_id}", response_model=ReleaseDetail, summary="Get one release")
async def get_release(release_id: UUID, session: Session, org_id: VerifiedOrg) -> ReleaseDetail:
    try:
        return await service.get_release_detail(session, org_id, release_id)
    except service.ReleaseError as exc:
        raise _http(exc) from exc


@router.post(
    "",
    response_model=ReleaseDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a release from two published versions",
)
async def create_release(
    payload: ReleaseCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ReleaseDetail:
    try:
        return await service.create_release(session, org_id, payload)
    except service.ReleaseError as exc:
        raise _http(exc) from exc


@router.post(
    "/preview",
    response_model=ReleaseGateVerdict,
    summary="CI gate — evaluate two descriptors without persisting anything",
)
async def preview_release(
    payload: ReleasePreviewRequest,
    org_id: VerifiedOrg,
) -> ReleaseGateVerdict:
    _ = org_id
    return await service.preview_release_request(payload)


@router.post(
    "/preview/review-brief",
    response_model=ReleaseReviewBrief,
    summary="Deterministic review brief for two descriptors without persisting anything",
)
async def preview_review_brief(
    payload: ReleasePreviewRequest,
    org_id: VerifiedOrg,
) -> ReleaseReviewBrief:
    _ = org_id
    return service.preview_review_brief(payload.before_descriptor, payload.after_descriptor)


@router.get(
    "/{release_id}/review-brief",
    response_model=ReleaseReviewBrief,
    summary="Plain-language review brief derived from stored semantic changes",
)
async def get_review_brief(
    release_id: UUID, session: Session, org_id: VerifiedOrg
) -> ReleaseReviewBrief:
    try:
        return await service.get_review_brief(session, org_id, release_id)
    except service.ReleaseError as exc:
        raise _http(exc) from exc


@router.post(
    "/{release_id}/transition",
    response_model=ReleaseDetail,
    summary="Advance the release state machine",
)
async def transition_release(
    release_id: UUID,
    payload: ReleaseTransitionRequest,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ReleaseDetail:
    try:
        return await service.transition_release(session, org_id, release_id, payload)
    except service.ReleaseError as exc:
        raise _http(exc) from exc


@router.post(
    "/{release_id}/changes/{change_id}/adjudicate",
    response_model=SemanticChange,
    summary="Record a human override of an automatic materiality verdict",
)
async def adjudicate_change(
    release_id: UUID,
    change_id: UUID,
    payload: ChangeAdjudicateRequest,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> SemanticChange:
    try:
        return await service.adjudicate_change(session, org_id, release_id, change_id, payload)
    except service.ReleaseError as exc:
        raise _http(exc) from exc
