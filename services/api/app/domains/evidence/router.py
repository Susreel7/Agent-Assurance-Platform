"""Evidence HTTP handlers. Thin by rule — every one delegates immediately.

Note what is absent: there is no PATCH, no PUT and no DELETE. ``evidence_events`` is
append-only and the database enforces it. A correction is a new event, not an edit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import Session, VerifiedOrg
from app.api.route import TransactionalRoute
from app.domains.evidence import service
from app.domains.evidence.schemas import (
    ChainVerification,
    EvidenceBatchOut,
    EvidenceBatchRequest,
    EvidenceKind,
    EvidenceOutcome,
    EvidencePage,
    EvidenceRecord,
    InclusionProof,
    IngestResult,
    SealResult,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.EventNotFoundError: status.HTTP_404_NOT_FOUND,
    service.BatchNotFoundError: status.HTTP_404_NOT_FOUND,
    service.EventNotAnchoredError: status.HTTP_409_CONFLICT,
}


def _http(exc: service.EvidenceError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


class KindCounts(BaseModel):
    counts: dict[str, int]
    total: int


class BatchPage(BaseModel):
    items: list[EvidenceBatchOut]
    total: int
    limit: int
    offset: int


class CheckpointOut(BaseModel):
    id: UUID
    tree_size: int
    root: str
    published_to: str
    published_at: datetime
    signature: str | None


# ----------------------------------------------------------------------
# Ingest
# ----------------------------------------------------------------------


@router.post(
    "",
    response_model=IngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Record governed facts",
)
async def ingest(
    payload: EvidenceBatchRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> IngestResult:
    """Bulk ingest from the collector.

    Deliberately not guarded by ``WriteEnabled``. A lapsed licence degrades the product
    to read-only, but refusing evidence would leave a permanent gap in an audit trail to
    settle a billing dispute — and the gap outlives the dispute. See ``api/deps.py``.

    Returns 202 rather than 201: rows can be rejected individually, so the response is
    an acceptance report rather than a created resource.
    """
    return await service.record_events(session, org_id, payload.events)


@router.post(
    "/one",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Record a single governed fact",
)
async def ingest_one(
    payload: EvidenceRecord,
    session: Session,
    org_id: VerifiedOrg,
) -> dict[str, UUID]:
    try:
        event_id = await service.record_one(session, org_id, payload)
    except service.EvidenceError as exc:
        raise _http(exc) from exc
    return {"id": event_id}


# ----------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------


@router.get("", response_model=EvidencePage, summary="Search evidence")
async def list_evidence(
    session: Session,
    org_id: VerifiedOrg,
    kind: Annotated[list[EvidenceKind] | None, Query()] = None,
    outcome: Annotated[list[EvidenceOutcome] | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
    engagement_id: Annotated[UUID | None, Query()] = None,
    customer_id: Annotated[UUID | None, Query()] = None,
    region: Annotated[str | None, Query(max_length=64)] = None,
    data_class: Annotated[str | None, Query(max_length=64)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    unsealed_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidencePage:
    items, total = await service.list_events(
        session,
        org_id,
        kinds=[k.value for k in kind] if kind else None,
        outcomes=[o.value for o in outcome] if outcome else None,
        agent_id=agent_id,
        engagement_id=engagement_id,
        customer_id=customer_id,
        region=region,
        data_class=data_class,
        since=since,
        until=until,
        unsealed_only=unsealed_only,
        limit=limit,
        offset=offset,
    )
    return EvidencePage(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/-/kind-counts",
    response_model=KindCounts,
    summary="Facet counts by evidence kind",
)
async def kind_counts(
    session: Session,
    org_id: VerifiedOrg,
    since: Annotated[datetime | None, Query()] = None,
) -> KindCounts:
    """Path is ``/-/`` so it cannot collide with an event UUID."""
    counts = await service.kind_counts(session, org_id, since=since)
    return KindCounts(counts=counts, total=sum(counts.values()))


# ----------------------------------------------------------------------
# Chain
# ----------------------------------------------------------------------


@router.get(
    "/-/batches",
    response_model=BatchPage,
    summary="List sealed batches, newest first",
)
async def list_batches(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BatchPage:
    items, total = await service.list_batches(session, org_id, limit=limit, offset=offset)
    return BatchPage(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/-/verify",
    response_model=ChainVerification,
    summary="Re-derive every Merkle root and chain link",
)
async def verify_chain(
    session: Session,
    org_id: VerifiedOrg,
    from_seq: Annotated[int | None, Query(ge=0)] = None,
    max_batches: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> ChainVerification:
    """What an auditor is really asking when they ask whether the log can be trusted.

    Recomputes rather than trusting stored values, so a database edit that updated a
    root alongside an event is still detected.
    """
    return await service.verify_chain(session, org_id, from_seq=from_seq, max_batches=max_batches)


@router.get(
    "/{event_id}/proof",
    response_model=InclusionProof,
    summary="Inclusion proof for one event",
)
async def inclusion_proof(
    event_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    occurred_at: Annotated[
        datetime | None,
        Query(description="Prunes the search to one partition. Supply it when known."),
    ] = None,
) -> InclusionProof:
    """The audit path carries sibling digests only, never sibling content — which is
    what makes it safe to publish a per-event proof to a shared trust portal."""
    try:
        return await service.build_inclusion_proof(
            session, org_id, event_id, occurred_at=occurred_at
        )
    except service.EvidenceError as exc:
        raise _http(exc) from exc


@router.post(
    "/-/seal",
    response_model=SealResult,
    summary="Seal pending events into a batch",
)
async def seal(
    session: Session,
    org_id: VerifiedOrg,
) -> SealResult:
    """Normally the worker's job. Exposed because a demo, and an operator diagnosing a
    stalled sealer, both need to force a cycle without waiting for the cadence."""
    try:
        return await service.seal_pending(session, org_id, sealed_by="person:api")
    except service.EvidenceError as exc:
        raise _http(exc) from exc


@router.post(
    "/-/checkpoints",
    response_model=CheckpointOut,
    status_code=status.HTTP_201_CREATED,
    summary="Publish the chain head to a named audience",
)
async def publish_checkpoint(
    session: Session,
    org_id: VerifiedOrg,
    published_to: Annotated[str, Query(max_length=128)],
    external_ref: Annotated[str | None, Query(max_length=256)] = None,
) -> CheckpointOut:
    """Once a customer holds a checkpoint we cannot rewrite history before it, even
    with full database access. That is why publishing names its recipient."""
    try:
        result = await service.publish_checkpoint(
            session, org_id, published_to=published_to, external_ref=external_ref
        )
    except service.EvidenceError as exc:
        raise _http(exc) from exc
    return CheckpointOut(**result)


@router.get(
    "/-/checkpoints",
    response_model=list[CheckpointOut],
    summary="List published checkpoints",
)
async def list_checkpoints(
    session: Session,
    org_id: VerifiedOrg,
    published_to: Annotated[str | None, Query(max_length=128)] = None,
) -> list[CheckpointOut]:
    rows = await service.list_checkpoints(session, org_id, published_to=published_to)
    return [CheckpointOut(**r) for r in rows]
