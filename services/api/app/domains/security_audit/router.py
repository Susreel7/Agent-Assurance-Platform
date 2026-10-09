"""Security audit: read the trail, submit machine-generated events.

There is no update endpoint and no delete endpoint. That is the feature — retention is a
partition drop performed by the operator, not an API a compromised session can call.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    CollectorAuth,
    PermissionGuard,
    Session,
    VerifiedOrg,
    WorkloadSession,
    enforce_collector,
)
from app.api.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, decode_time_cursor
from app.api.route import TransactionalRoute
from app.domains.security_audit import service
from app.domains.security_audit.schemas import (
    AuditDigest,
    AuditPage,
    AuditQuery,
    AuditRecord,
    Category,
    Outcome,
    Severity,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.BatchTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    service.WindowTooWideError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _http(exc: service.SecurityAuditError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get(
    "/events",
    response_model=AuditPage,
    summary="Read the audit trail",
    dependencies=[PermissionGuard("audit:read")],
)
async def list_events(
    session: Session,
    org_id: VerifiedOrg,
    query: Annotated[AuditQuery, Query()] = AuditQuery(),
    cursor: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> AuditPage:
    """Newest-first, keyset-paginated.

    There is no page number and no total. `OFFSET n` makes Postgres produce and discard
    `n` rows, so on this table the cost of a page would grow with how deep the reader has
    gone; a cursor is an index seek at any depth. The response carries `next_cursor` or
    nothing, which is what a keyset listing can honestly say.
    """
    return await service.list_events(
        session,
        org_id,
        query,
        page_size=page_size,
        cursor=decode_time_cursor(cursor),
    )


@router.get(
    "/digest",
    response_model=AuditDigest,
    summary="Counts by category and severity",
    dependencies=[PermissionGuard("audit:read")],
)
async def digest(
    session: Session,
    org_id: VerifiedOrg,
    days: Annotated[int, Query(ge=1, le=service.MAX_DIGEST_DAYS)] = service.DEFAULT_DIGEST_DAYS,
) -> AuditDigest:
    """The security overview's headline figures, over a bounded window.

    Computed live rather than cached, which is affordable only because the window prunes
    to one or two monthly partitions. That is why `days` has a ceiling.
    """
    try:
        return await service.digest(session, org_id, days=days)
    except service.SecurityAuditError as exc:
        raise _http(exc) from exc


@router.get(
    "/events/for-target/{target_id}",
    response_model=AuditPage,
    summary="Everything that happened to one resource",
    dependencies=[PermissionGuard("audit:read")],
)
async def list_for_target(
    target_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    cursor: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    category: Category | None = None,
    severity: Severity | None = None,
    outcome: Outcome | None = None,
) -> AuditPage:
    """The history panel on a server, connection or member page.

    Its own route rather than a filter on the listing because `target_id` has a dedicated
    index; routing it through the general endpoint would leave the choice of index to
    whichever other filters the caller happened to include.
    """
    return await service.list_events(
        session,
        org_id,
        AuditQuery(
            target_id=target_id,
            category=category,
            severity=severity,
            outcome=outcome,
        ),
        page_size=page_size,
        cursor=decode_time_cursor(cursor),
    )


@router.post(
    "/events",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit audit events (gateway and worker path)",
)
async def submit_events(
    payload: list[AuditRecord],
    collector: CollectorAuth,
    session: WorkloadSession,
) -> dict[str, int]:
    """Enforcement decisions made outside the API, appended to the same trail.

    The gateway denies a tool call in the data path and the console must be able to show
    that denial next to the grant change that caused it. Both therefore land in one table.

    The organisation comes from the presented credential, never from a header: a workload
    must not be able to write events into another tenant's evidence.
    """
    workload = enforce_collector(collector, scope="audit:write", module="router")
    try:
        appended = await service.record_many(session, workload.org_id, payload)
    except service.SecurityAuditError as exc:
        raise _http(exc) from exc
    return {"appended": appended}
