"""Framework HTTP handlers. Thin by rule — every one delegates immediately."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.deps import Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.frameworks import service
from app.domains.frameworks.schemas import (
    ControlMappingOut,
    ControlMappingUpsert,
    CoverageByFramework,
    FrameworkControlOut,
    FrameworkDetail,
    FrameworkSummary,
    ImportResult,
    QuestionnaireImport,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.FrameworkNotFoundError: status.HTTP_404_NOT_FOUND,
    service.ControlNotFoundError: status.HTTP_404_NOT_FOUND,
    service.FrameworkSlugTakenError: status.HTTP_409_CONFLICT,
    service.FrameworkReadOnlyError: status.HTTP_403_FORBIDDEN,
    service.QuestionnaireImportError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _http(exc: service.FrameworkError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get("", response_model=list[FrameworkSummary], summary="List visible frameworks")
async def list_frameworks(session: Session, org_id: VerifiedOrg) -> list[FrameworkSummary]:
    return await service.list_frameworks(session, org_id)


@router.get("/{framework_id}", response_model=FrameworkDetail, summary="Get one framework")
async def get_framework(
    framework_id: UUID, session: Session, org_id: VerifiedOrg
) -> FrameworkDetail:
    try:
        return await service.get_framework_detail(session, org_id, framework_id)
    except service.FrameworkError as exc:
        raise _http(exc) from exc


@router.get(
    "/{framework_id}/controls",
    response_model=list[FrameworkControlOut],
    summary="List controls in a framework",
)
async def list_controls(
    framework_id: UUID, session: Session, org_id: VerifiedOrg
) -> list[FrameworkControlOut]:
    try:
        return await service.list_framework_controls(session, org_id, framework_id)
    except service.FrameworkError as exc:
        raise _http(exc) from exc


@router.post(
    "",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import a tenant questionnaire as a framework",
)
async def import_questionnaire(
    payload: QuestionnaireImport,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ImportResult:
    try:
        return await service.import_questionnaire(session, org_id, payload)
    except service.FrameworkError as exc:
        raise _http(exc) from exc


@router.put(
    "/controls/{control_id}/mappings",
    response_model=ControlMappingOut,
    summary="Attach an evidence kind to a control",
)
async def map_control(
    control_id: UUID,
    payload: ControlMappingUpsert,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ControlMappingOut:
    try:
        return await service.map_control(session, org_id, control_id, payload)
    except service.FrameworkError as exc:
        raise _http(exc) from exc


@router.get(
    "/{framework_id}/coverage",
    response_model=CoverageByFramework,
    summary="Mapping coverage for one framework",
)
async def get_coverage(
    framework_id: UUID, session: Session, org_id: VerifiedOrg
) -> CoverageByFramework:
    try:
        return await service.compute_coverage(session, org_id, framework_id)
    except service.FrameworkError as exc:
        raise _http(exc) from exc
