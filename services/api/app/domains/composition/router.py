"""Composition HTTP handlers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.assurance import service as assurance_service
from app.domains.assurance.rule_gaps import RuleGapReport
from app.domains.assurance.schemas import AgentProbeStatusOut
from app.domains.composition import service
from app.domains.composition.schemas import CompositionSummary, ReconciliationPage
from app.domains.registry import service as registry_service

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.CompositionAgentNotFoundError: status.HTTP_404_NOT_FOUND,
    service.CompositionVersionNotFoundError: status.HTTP_404_NOT_FOUND,
}


def _http(exc: service.CompositionError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get(
    "/{agent_id}/versions/{version_id}/composition",
    response_model=CompositionSummary,
    summary="Declared composition for one version",
)
async def get_version_composition(
    agent_id: UUID,
    version_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> CompositionSummary:
    try:
        return await service.get_composition_summary(
            session, org_id, agent_id, version_id, window_days=days
        )
    except service.CompositionError as exc:
        raise _http(exc) from exc


@router.get(
    "/{agent_id}/composition/reconciliation",
    response_model=ReconciliationPage,
    summary="Reconcile declared composition with observed runtime usage",
)
async def get_reconciliation(
    agent_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    version_id: Annotated[UUID | None, Query()] = None,
) -> ReconciliationPage:
    try:
        page = await service.reconcile_agent(
            session,
            org_id,
            agent_id,
            window_days=days,
            version_id=version_id,
        )
    except service.CompositionError as exc:
        raise _http(exc) from exc
    await assurance_service.record_reconciliation_findings(
        session, org_id, agent_id, page.agent_version_id, page.elements
    )
    return page


@router.get(
    "/{agent_id}/versions/{version_id}/probe-status",
    response_model=AgentProbeStatusOut,
    summary="Last probe run per suite for one version",
)
async def get_probe_status(
    agent_id: UUID,
    version_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> AgentProbeStatusOut:
    try:
        await registry_service.get_version_descriptor(session, org_id, version_id)
    except registry_service.RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await assurance_service.get_agent_probe_status(session, org_id, agent_id, version_id)


@router.get(
    "/{agent_id}/versions/{version_id}/rule-gaps",
    response_model=RuleGapReport,
    summary="Template-mapped obligation gaps for one version",
)
async def get_rule_gaps(
    agent_id: UUID,
    version_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    framework: Annotated[str | None, Query()] = None,
) -> RuleGapReport:
    try:
        return await assurance_service.compute_rule_gaps(
            session,
            org_id,
            agent_id,
            version_id,
            framework_slug=framework,
        )
    except registry_service.RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{agent_id}/versions/{version_id}/rule-gaps/export",
    summary="Export rule gap report as markdown",
)
async def export_rule_gaps(
    agent_id: UUID,
    version_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    framework: Annotated[str | None, Query()] = None,
) -> Response:
    try:
        body = await assurance_service.export_rule_gaps(
            session,
            org_id,
            agent_id,
            version_id,
            framework_slug=framework,
        )
    except registry_service.RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(content=body, media_type="text/markdown; charset=utf-8")


@router.post(
    "/{agent_id}/versions/{version_id}/composition/reconcile",
    response_model=ReconciliationPage,
    summary="Run reconciliation for one version (writes findings, never mutates descriptor)",
)
async def post_reconcile_version(
    agent_id: UUID,
    version_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> ReconciliationPage:
    try:
        page = await service.reconcile_agent(
            session,
            org_id,
            agent_id,
            window_days=days,
            version_id=version_id,
        )
    except service.CompositionError as exc:
        raise _http(exc) from exc
    await assurance_service.record_reconciliation_findings(
        session, org_id, agent_id, page.agent_version_id, page.elements
    )
    return page
