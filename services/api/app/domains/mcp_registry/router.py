"""MCP registry: servers, discovery, capability review, grants and the tool decision.

Two audiences share this router and they need different guarantees.

A human in the console registers servers, reviews capabilities and grants access. Every
one of those is a `member:`-authenticated write behind a permission.

The gateway asks one question — may this call proceed — on the hot path, authenticated by
a workload credential rather than a session. That endpoint reads its subject from the
credential, never from the body, so a workload cannot ask about access it does not have.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    CollectorAuth,
    CurrentMember,
    PermissionGuard,
    Session,
    VerifiedOrg,
    WorkloadSession,
    WriteGuard,
    enforce_collector,
)
from app.api.route import TransactionalRoute
from app.domains.mcp_registry import service
from app.domains.mcp_registry.schemas import (
    CapabilityOut,
    CapabilityReview,
    GrantCreate,
    GrantOut,
    Quarantine,
    ServerDetail,
    ServerOut,
    ServerPage,
    ServerRegister,
    ServerState,
    ServerUpdate,
    SnapshotOut,
    SnapshotSubmit,
    ToolDecision,
    ToolDecisionRequest,
    UsageIngest,
    UsageRollup,
)
from app.domains.members import repository as member_repo

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.ServerNotFoundError: status.HTTP_404_NOT_FOUND,
    service.SnapshotNotFoundError: status.HTTP_404_NOT_FOUND,
    service.CapabilityNotFoundError: status.HTTP_404_NOT_FOUND,
    service.GrantNotFoundError: status.HTTP_404_NOT_FOUND,
    service.DuplicateServerError: status.HTTP_409_CONFLICT,
    service.AlreadyApprovedError: status.HTTP_409_CONFLICT,
    service.SnapshotNotOnServerError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    service.EnvironmentNotEnabledError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    service.NothingToApproveError: status.HTTP_409_CONFLICT,
}


def _http(exc: service.McpRegistryError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get(
    "/servers",
    response_model=ServerPage,
    summary="List MCP servers",
    dependencies=[PermissionGuard("mcp:read")],
)
async def list_servers(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    state: ServerState | None = None,
    trust_tier: str | None = None,
) -> ServerPage:
    return await service.list_servers(
        session,
        org_id,
        limit=limit,
        offset=offset,
        state=state,
        trust_tier=trust_tier,
    )


@router.post(
    "/servers",
    response_model=ServerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register an MCP server",
    dependencies=[PermissionGuard("mcp:write"), WriteGuard],
)
async def register_server(
    payload: ServerRegister,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> ServerOut:
    """Registration governs a server; it does not grant it.

    The server lands in `draft` with no approved snapshot, so every tool call against it
    is denied until its capabilities are discovered and approved.
    """
    try:
        return await service.register_server(session, org_id, payload, actor=member.label)
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.get(
    "/servers/{server_id}",
    response_model=ServerDetail,
    summary="One server with capabilities, drift and usage",
    dependencies=[PermissionGuard("mcp:read")],
)
async def get_server(
    server_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> ServerDetail:
    try:
        return await service.server_detail(session, org_id, server_id)
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.patch(
    "/servers/{server_id}",
    response_model=ServerOut,
    summary="Update a server",
    dependencies=[PermissionGuard("mcp:write"), WriteGuard],
)
async def update_server(
    server_id: UUID,
    payload: ServerUpdate,
    session: Session,
    org_id: VerifiedOrg,
) -> ServerOut:
    try:
        return await service.update_server(session, org_id, server_id, payload)
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.post(
    "/servers/{server_id}/snapshots",
    response_model=SnapshotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a discovery result",
    dependencies=[PermissionGuard("mcp:discover"), WriteGuard],
)
async def submit_snapshot(
    server_id: UUID,
    payload: SnapshotSubmit,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> SnapshotOut:
    """Record what a server currently advertises.

    Idempotent by content: re-submitting an unchanged capability set returns the existing
    snapshot with a fresh `discovered_at` rather than adding a row. A server polled every
    five minutes for a year therefore produces one snapshot, not a hundred thousand.

    Recording is not approving. A submission that differs from the approved snapshot
    flips the server's health to `drift` and waits for a reviewer.
    """
    try:
        return await service.submit_snapshot(
            session, org_id, server_id, payload, actor=member.label
        )
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.post(
    "/servers/{server_id}/snapshots/{snapshot_id}/approve",
    response_model=SnapshotOut,
    summary="Approve a snapshot",
    dependencies=[PermissionGuard("mcp:approve"), WriteGuard],
)
async def approve_snapshot(
    server_id: UUID,
    snapshot_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> SnapshotOut:
    """Make this snapshot the one grants resolve against.

    Grants pinned to the previous snapshot keep resolving against it. That is deliberate:
    approving a new capability set must not silently widen access somebody already
    reviewed. Re-pinning those grants is a separate, visible decision.
    """
    try:
        return await service.approve_snapshot(
            session, org_id, server_id, snapshot_id, actor=member.label
        )
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.patch(
    "/capabilities/{capability_id}",
    response_model=CapabilityOut,
    summary="Record what a capability actually does",
    dependencies=[PermissionGuard("mcp:approve"), WriteGuard],
)
async def review_capability(
    capability_id: UUID,
    payload: CapabilityReview,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> CapabilityOut:
    """A human's verdict, kept alongside the server's own claim rather than replacing it.

    When a server declares `readOnlyHint` and review finds a write, both are retained and
    the response reports `annotation_mismatch`. A server lying about its annotations is
    the case this registry exists to catch, so that evidence is not overwritten.
    """
    try:
        return await service.review_capability(
            session, org_id, capability_id, payload, actor=member.label
        )
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.get(
    "/servers/{server_id}/grants",
    response_model=list[GrantOut],
    summary="Who may call this server",
    dependencies=[PermissionGuard("mcp:read")],
)
async def list_grants(
    server_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[GrantOut]:
    return await service.list_grants(session, org_id, server_id)


@router.post(
    "/servers/{server_id}/grants",
    response_model=GrantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Grant access to a server or one capability",
    dependencies=[PermissionGuard("mcp:grant"), WriteGuard],
)
async def grant(
    server_id: UUID,
    payload: GrantCreate,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> GrantOut:
    """Pinned to the currently approved snapshot unless the caller opts out.

    Without pinning, a grant reads whichever snapshot is approved at call time, so a
    server that adds a tool and gets re-approved would hand that tool to every existing
    grant. Pinning is what makes new capabilities require a new decision.
    """
    try:
        return await service.grant(session, org_id, server_id, payload, actor=member.label)
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.delete(
    "/grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a grant",
    dependencies=[PermissionGuard("mcp:grant"), WriteGuard],
)
async def revoke_grant(
    grant_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> None:
    try:
        await service.revoke_grant(session, org_id, grant_id)
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.post(
    "/servers/{server_id}/quarantine",
    response_model=ServerOut,
    summary="Stop a server immediately",
    dependencies=[PermissionGuard("mcp:quarantine"), WriteGuard],
)
async def quarantine(
    server_id: UUID,
    payload: Quarantine,
    session: Session,
    org_id: VerifiedOrg,
) -> ServerOut:
    """One write, and the next tool call against this server is denied.

    Grants are left intact. Revoking them one by one is the slow version of the same
    intent and loses the state needed to restore access afterwards.
    """
    try:
        return await service.quarantine(session, org_id, server_id, payload)
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.delete(
    "/servers/{server_id}/quarantine",
    response_model=ServerOut,
    summary="Lift a quarantine",
    dependencies=[PermissionGuard("mcp:quarantine"), WriteGuard],
)
async def release(
    server_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> ServerOut:
    try:
        return await service.release(session, org_id, server_id)
    except service.McpRegistryError as exc:
        raise _http(exc) from exc


@router.get(
    "/servers/{server_id}/usage",
    response_model=list[UsageRollup],
    summary="Daily usage rollup for a server",
    dependencies=[PermissionGuard("mcp:read")],
)
async def usage(
    server_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> list[UsageRollup]:
    return await service.usage(session, org_id, server_id, days=days)


@router.post(
    "/decide",
    response_model=ToolDecision,
    summary="May this tool call proceed (gateway path)",
)
async def decide(
    payload: ToolDecisionRequest,
    collector: CollectorAuth,
    session: WorkloadSession,
) -> ToolDecision:
    """The question asked before every MCP tool invocation.

    The subject is taken from the presented workload credential, not from the body. A
    caller must not be able to ask whether *another* agent could make this call and then
    act on the answer.

    A denial always carries a distinct `reason_code`. "Blocked" with no cause is what
    makes an operator switch enforcement off.
    """
    # MCP mediation is the gateway's job, so this rides the `router` module rather than a
    # module of its own: the process that proxies tool calls is the process that holds a
    # router credential, and inventing an `mcp` module would mean every gateway needed a
    # second credential to do one job.
    workload = enforce_collector(collector, scope="mcp:invoke", module="router")

    # A grant may name the credential, the agent or the project. All three are read from
    # the verified credential, so the widest thing a caller can ask about is itself.
    subjects: list[tuple[str, UUID]] = [
        ("workload", workload.credential_id),
        ("project", workload.project_id),
    ]
    if workload.agent_id is not None:
        subjects.append(("agent", workload.agent_id))
    if workload.member_id is not None:
        subjects.append(("member", workload.member_id))
        subjects.extend(
            ("team", team_id)
            for team_id in await member_repo.team_ids_for_member(
                session, workload.org_id, workload.member_id
            )
        )

    decision = await service.decide(
        session,
        workload.org_id,
        server_slug=payload.server_slug,
        capability_name=payload.capability_name,
        subjects=subjects,
        environment=workload.environment.value,
    )
    return decision.model_copy(
        update={
            "workload_credential_id": workload.credential_id,
            "project_id": workload.project_id,
            "agent_id": workload.agent_id,
            "member_id": workload.member_id,
            "environment": workload.environment,
        }
    )


@router.post(
    "/usage",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Merge daily usage aggregates (worker path)",
)
async def ingest_usage(
    payload: list[UsageIngest],
    collector: CollectorAuth,
    session: WorkloadSession,
) -> dict[str, int]:
    """Aggregates from the Observe worker, never individual calls.

    At the tool-call volumes this platform targets a per-call control-plane row is not an
    option. The per-call record lives in ClickHouse behind Observe; this is the daily
    rollup the console and the grant reviewer read. Counts add rather than replace, so a
    re-delivered window neither double-counts nor resets.
    """
    # The Observe worker owns this: it is the process that already reads the per-call
    # records, so it carries the `observe` module rather than a registry-specific one.
    workload = enforce_collector(collector, scope="mcp:usage", module="observe")
    merged = await service.ingest_usage(session, workload.org_id, payload)
    return {"merged": merged}
