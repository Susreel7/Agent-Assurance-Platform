"""MCP registry behaviour: discovery, drift, review, grants and the tool-call decision.

Three ideas carry this domain.

**A snapshot is content-addressed.** Discovery hashes the capability set it found; an
unchanged server re-discovered a thousand times produces one snapshot row with a moving
``discovered_at``. That is what keeps the table bounded under continuous polling.

**A grant is pinned to a snapshot.** When a server adds a tool after approval, existing
grants do not reach it. This is the defence against the rug-pull: a benign MCP server
that ships `read_file` on Monday and `exfiltrate_secrets` on Tuesday gains nothing,
because every live grant still points at Monday's snapshot.

**Declared is not verified.** An MCP server advertises its own ``readOnlyHint`` and
``destructiveHint``. A reviewer records what the tool *actually* does. When the two
disagree we keep both and surface the mismatch, because a server lying about its own
annotations is exactly the case this registry exists to catch.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_registry import McpCapability, McpServer, McpSnapshot
from app.domains.mcp_registry import repository as repo
from app.domains.mcp_registry.schemas import (
    CapabilityDeclared,
    CapabilityKind,
    CapabilityOut,
    CapabilityReview,
    GrantCreate,
    GrantOut,
    HealthState,
    Quarantine,
    RiskTier,
    ServerDetail,
    ServerOut,
    ServerPage,
    ServerRegister,
    ServerState,
    ServerSummary,
    ServerUpdate,
    SnapshotOut,
    SnapshotSubmit,
    ToolDecision,
    UsageIngest,
    UsageRollup,
)

USAGE_WINDOW_DAYS = 7

# Rows keyed on a capability that was not attributed to an agent or a member. See
# migration 0017: a primary key cannot hold an expression, so the absence is a value.
UNATTRIBUTED = UUID("00000000-0000-0000-0000-000000000000")

_DANGEROUS_RISKS = frozenset({RiskTier.HIGH.value, RiskTier.CRITICAL.value})


class McpRegistryError(Exception):
    """Base class so the router maps one exception family."""


class ServerNotFoundError(McpRegistryError):
    pass


class DuplicateServerError(McpRegistryError):
    pass


class SnapshotNotFoundError(McpRegistryError):
    pass


class CapabilityNotFoundError(McpRegistryError):
    pass


class GrantNotFoundError(McpRegistryError):
    pass


class AlreadyApprovedError(McpRegistryError):
    """The snapshot carries an approval already, and an approval never moves."""


class SnapshotNotOnServerError(McpRegistryError):
    pass


class EnvironmentNotEnabledError(McpRegistryError):
    """A grant reaches an environment the server itself is not enabled for."""


class NothingToApproveError(McpRegistryError):
    """Approval was requested for a server that has never been discovered."""


def capability_digest(capabilities: list[CapabilityDeclared]) -> bytes:
    """Content address for a capability set.

    Covers name, kind, input-schema digest and the four declared annotation hints —
    every field a decision reads. Order is normalised so two discoveries that return the
    same tools in a different order produce the same digest and therefore one snapshot.

    Titles are deliberately excluded: a server rewording a tool's human-readable title
    has not changed what the tool can do, and treating that as drift would train
    reviewers to click through drift banners.
    """
    parts = sorted(
        "\x1f".join(
            (
                capability.kind.value,
                capability.name,
                capability.input_schema_digest or "",
                _tri(capability.declared_read_only),
                _tri(capability.declared_destructive),
                _tri(capability.declared_idempotent),
                _tri(capability.declared_open_world),
            )
        )
        for capability in capabilities
    )
    return hashlib.sha256("\x1e".join(parts).encode()).digest()


def _tri(value: bool | None) -> str:
    """Three-state annotation as a digest token.

    ``None`` must not collapse into ``False``: "the server did not say" and "the server
    said no" are different claims, and only the first is grounds for asking.
    """
    if value is None:
        return "u"
    return "t" if value else "f"


def _mismatch(capability: McpCapability) -> bool:
    """The server's own annotation contradicts what review found."""
    if capability.declared_read_only is True and capability.verified_write:
        return True
    return capability.declared_destructive is False and capability.verified_irreversible


def _capability_out(capability: McpCapability) -> CapabilityOut:
    return CapabilityOut(
        id=capability.id,
        snapshot_id=capability.snapshot_id,
        server_id=capability.server_id,
        kind=CapabilityKind(capability.kind),
        name=capability.name,
        title=capability.title,
        input_schema_digest_hex=(
            capability.input_schema_digest.hex() if capability.input_schema_digest else None
        ),
        declared_read_only=capability.declared_read_only,
        declared_destructive=capability.declared_destructive,
        declared_idempotent=capability.declared_idempotent,
        declared_open_world=capability.declared_open_world,
        verified_risk=RiskTier(capability.verified_risk),
        verified_write=capability.verified_write,
        verified_irreversible=capability.verified_irreversible,
        review_note=capability.review_note,
        reviewed_by=capability.reviewed_by,
        reviewed_at=capability.reviewed_at,
        annotation_mismatch=_mismatch(capability),
    )


def _snapshot_out(snapshot: McpSnapshot) -> SnapshotOut:
    return SnapshotOut(
        id=snapshot.id,
        server_id=snapshot.server_id,
        capability_digest_hex=snapshot.capability_digest.hex(),
        protocol_version=snapshot.protocol_version,
        source=snapshot.source,
        tool_count=snapshot.tool_count,
        resource_count=snapshot.resource_count,
        prompt_count=snapshot.prompt_count,
        discovered_at=snapshot.discovered_at,
        discovered_by=snapshot.discovered_by,
        approved_at=snapshot.approved_at,
        approved_by=snapshot.approved_by,
        superseded_at=snapshot.superseded_at,
    )


def _drifted(server: McpServer) -> bool:
    """Observed capabilities differ from what was approved.

    A server with no observation yet is not drifted — it is undiscovered, which the
    console shows as unknown health rather than as a change to review.
    """
    if server.observed_snapshot_id is None:
        return False
    return server.observed_snapshot_id != server.approved_snapshot_id


async def register_server(
    session: AsyncSession,
    org_id: UUID,
    payload: ServerRegister,
    *,
    actor: str,
) -> ServerOut:
    """Record a server. Registration grants nothing.

    A newly registered server lands in ``draft`` with no approved snapshot, so
    ``decide`` denies every call against it until someone discovers its capabilities and
    approves them. Registration is an intent to govern, not a permission.
    """
    try:
        server = await repo.insert_server(
            session,
            org_id,
            {
                "slug": payload.slug,
                "name": payload.name,
                "description": payload.description,
                "transport": payload.transport.value,
                "endpoint_url": payload.endpoint_url,
                "command": payload.command,
                "owner_team_id": payload.owner_team_id,
                "connection_id": payload.connection_id,
                "trust_tier": payload.trust_tier.value,
                "state": ServerState.DRAFT.value,
                "health": HealthState.UNKNOWN.value,
                "environments": [item.value for item in payload.environments],
                "requires_approval_for_writes": payload.requires_approval_for_writes,
                "created_by": actor,
            },
        )
    except IntegrityError as exc:
        raise DuplicateServerError(payload.slug) from exc
    return ServerOut.model_validate(server)


async def get_server(session: AsyncSession, org_id: UUID, server_id: UUID) -> ServerOut:
    server = await repo.get_server(session, org_id, server_id)
    if server is None:
        raise ServerNotFoundError(str(server_id))
    return ServerOut.model_validate(server)


async def update_server(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    payload: ServerUpdate,
) -> ServerOut:
    values = payload.model_dump(exclude_unset=True)
    if "trust_tier" in values and values["trust_tier"] is not None:
        values["trust_tier"] = payload.trust_tier.value if payload.trust_tier else None
    if "risk_tier" in values and values["risk_tier"] is not None:
        values["risk_tier"] = payload.risk_tier.value if payload.risk_tier else None
    if values.get("environments") is not None:
        values["environments"] = [item.value for item in payload.environments or []]
    values = {key: value for key, value in values.items() if value is not None}
    if not values:
        return await get_server(session, org_id, server_id)

    server = await repo.update_server(session, org_id, server_id, values)
    if server is None:
        raise ServerNotFoundError(str(server_id))
    return ServerOut.model_validate(server)


def _summary(row: tuple[McpServer, str | None, int, int, int, int, int]) -> ServerSummary:
    server, team_name, tools, grants, dangerous, calls, denials = row
    return ServerSummary(
        server=ServerOut.model_validate(server),
        owner_team_name=team_name,
        tool_count=tools,
        grant_count=grants,
        dangerous_tool_count=dangerous,
        drifted=_drifted(server),
        calls_7d=calls,
        denials_7d=denials,
    )


async def list_servers(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    state: ServerState | None = None,
    trust_tier: str | None = None,
) -> ServerPage:
    since = datetime.now(UTC).date() - timedelta(days=USAGE_WINDOW_DAYS)
    rows, total = await repo.list_servers(
        session,
        org_id,
        limit=limit,
        offset=offset,
        state=state.value if state else None,
        trust_tier=trust_tier,
        since=since,
    )
    return ServerPage(
        items=[_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def submit_snapshot(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    payload: SnapshotSubmit,
    *,
    actor: str,
) -> SnapshotOut:
    """Record what discovery found. Recording is not approving.

    The server row is locked first. Submission reads the approved digest, compares, and
    may flip health to ``drift`` — two concurrent discovery runs racing through that
    read-compare-write would leave health matching neither snapshot.
    """
    server = await repo.lock_server(session, org_id, server_id)
    if server is None:
        raise ServerNotFoundError(str(server_id))

    digest = capability_digest(payload.capabilities)
    existing = await repo.find_snapshot_by_digest(session, org_id, server_id, digest)
    if existing is not None:
        # Same capability set as a snapshot we already hold. Move the clock, not the rows.
        existing = await repo.touch_snapshot_discovery(session, org_id, existing.id)
        await _settle_observation(session, org_id, server, existing.id)
        return _snapshot_out(existing)

    counts = dict.fromkeys((CapabilityKind.TOOL, CapabilityKind.RESOURCE, CapabilityKind.PROMPT), 0)
    for capability in payload.capabilities:
        counts[capability.kind] += 1

    snapshot = await repo.insert_snapshot(
        session,
        org_id,
        {
            "server_id": server_id,
            "capability_digest": digest,
            "protocol_version": payload.protocol_version,
            "source": payload.source,
            "tool_count": counts[CapabilityKind.TOOL],
            "resource_count": counts[CapabilityKind.RESOURCE],
            "prompt_count": counts[CapabilityKind.PROMPT],
            "discovered_by": actor,
        },
    )

    await repo.insert_capabilities(
        session,
        org_id,
        [
            {
                "snapshot_id": snapshot.id,
                "server_id": server_id,
                "kind": capability.kind.value,
                "name": capability.name,
                "title": capability.title,
                "input_schema_digest": (
                    bytes.fromhex(capability.input_schema_digest)
                    if capability.input_schema_digest
                    else None
                ),
                "declared_read_only": capability.declared_read_only,
                "declared_destructive": capability.declared_destructive,
                "declared_idempotent": capability.declared_idempotent,
                "declared_open_world": capability.declared_open_world,
                # Risk defaults pessimistically: an unreviewed capability is a write
                # until a human says otherwise, so a server cannot ship a destructive
                # tool and have it inherit a benign default.
                "verified_risk": RiskTier.MEDIUM.value,
                "verified_write": True,
            }
            for capability in payload.capabilities
        ],
    )

    await _settle_observation(session, org_id, server, snapshot.id)
    return _snapshot_out(snapshot)


async def _settle_observation(
    session: AsyncSession,
    org_id: UUID,
    server: McpServer,
    observed_snapshot_id: UUID,
) -> None:
    """Point the server at its latest observation and set health accordingly.

    Health is derived, never asserted by the caller: a server whose observation matches
    its approval is healthy, one that has never been approved stays unknown, and any
    divergence is ``drift`` regardless of which direction it moved in.
    """
    if server.approved_snapshot_id is None:
        health = HealthState.UNKNOWN
    elif observed_snapshot_id == server.approved_snapshot_id:
        health = HealthState.HEALTHY
    else:
        health = HealthState.DRIFT

    await repo.update_server(
        session,
        org_id,
        server.id,
        {
            "observed_snapshot_id": observed_snapshot_id,
            "health": health.value,
            "last_discovered_at": datetime.now(UTC),
        },
    )


async def approve_snapshot(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    snapshot_id: UUID,
    *,
    actor: str,
) -> SnapshotOut:
    """Make a snapshot the one grants resolve against.

    The previous approval is superseded rather than deleted. A grant pinned to it keeps
    resolving, which is deliberate: approving a new snapshot must not silently widen or
    narrow access that someone already reviewed. Re-pinning is a separate decision.
    """
    server = await repo.lock_server(session, org_id, server_id)
    if server is None:
        raise ServerNotFoundError(str(server_id))

    snapshot = await repo.get_snapshot(session, org_id, snapshot_id)
    if snapshot is None:
        raise SnapshotNotFoundError(str(snapshot_id))
    if snapshot.server_id != server_id:
        raise SnapshotNotOnServerError(str(snapshot_id))

    approved = await repo.approve_snapshot(session, org_id, snapshot_id, approved_by=actor)
    if approved is None:
        raise AlreadyApprovedError(str(snapshot_id))

    if server.approved_snapshot_id is not None and server.approved_snapshot_id != snapshot_id:
        await repo.supersede_snapshot(session, org_id, server.approved_snapshot_id)

    healthy = server.observed_snapshot_id == snapshot_id
    await repo.update_server(
        session,
        org_id,
        server_id,
        {
            "approved_snapshot_id": snapshot_id,
            "state": ServerState.APPROVED.value,
            "health": (HealthState.HEALTHY if healthy else HealthState.DRIFT).value,
        },
    )
    return _snapshot_out(approved)


async def review_capability(
    session: AsyncSession,
    org_id: UUID,
    capability_id: UUID,
    payload: CapabilityReview,
    *,
    actor: str,
) -> CapabilityOut:
    """Record what a tool actually does.

    Permitted on a capability inside an immutable snapshot because the trigger in
    migration 0017 exempts the review columns: what the server *said* is frozen
    evidence, what a human *concluded* is an opinion that may be corrected.
    """
    capability = await repo.review_capability(
        session,
        org_id,
        capability_id,
        {
            "verified_risk": payload.verified_risk.value,
            "verified_write": payload.verified_write,
            "verified_irreversible": payload.verified_irreversible,
            "review_note": payload.review_note,
            "reviewed_by": actor,
        },
    )
    if capability is None:
        raise CapabilityNotFoundError(str(capability_id))
    return _capability_out(capability)


async def server_detail(session: AsyncSession, org_id: UUID, server_id: UUID) -> ServerDetail:
    """The whole server page in one response.

    The console shows the server, its capability list, its grants and its drift banner
    together. Split across four endpoints this becomes four sequential requests for one
    view, and the drift diff needs both snapshots in the same place to say anything true.
    """
    since = datetime.now(UTC).date() - timedelta(days=USAGE_WINDOW_DAYS)
    rows, _ = await repo.list_servers(
        session, org_id, limit=1, offset=0, server_id=server_id, since=since
    )
    if not rows:
        raise ServerNotFoundError(str(server_id))
    summary = _summary(rows[0])
    server = rows[0][0]

    approved = (
        await repo.get_snapshot(session, org_id, server.approved_snapshot_id)
        if server.approved_snapshot_id
        else None
    )
    observed = (
        await repo.get_snapshot(session, org_id, server.observed_snapshot_id)
        if server.observed_snapshot_id
        else None
    )

    # The reviewer reads the approved set, because that is what grants resolve against.
    # The diff below is what makes the drift banner actionable.
    shown_snapshot_id = server.approved_snapshot_id or server.observed_snapshot_id
    capabilities = (
        await repo.list_capabilities(session, org_id, shown_snapshot_id)
        if shown_snapshot_id
        else []
    )

    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    if approved is not None and observed is not None and approved.id != observed.id:
        approved_rows = {row.name: row for row in capabilities}
        observed_rows = {
            row.name: row for row in await repo.list_capabilities(session, org_id, observed.id)
        }
        added = sorted(set(observed_rows) - set(approved_rows))
        removed = sorted(set(approved_rows) - set(observed_rows))
        changed = sorted(
            name
            for name in set(approved_rows) & set(observed_rows)
            if approved_rows[name].input_schema_digest != observed_rows[name].input_schema_digest
        )

    return ServerDetail(
        summary=summary,
        approved_snapshot=_snapshot_out(approved) if approved else None,
        observed_snapshot=_snapshot_out(observed) if observed else None,
        capabilities=[_capability_out(row) for row in capabilities],
        added_capability_names=added,
        removed_capability_names=removed,
        changed_capability_names=changed,
    )


async def grant(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    payload: GrantCreate,
    *,
    actor: str,
) -> GrantOut:
    """Give a subject access to a server or one of its capabilities.

    Pinning is the default. Without it a grant reads whichever snapshot is approved at
    call time, so approving a new snapshot would hand every existing grant whatever
    tools the server had added — the rug-pull this registry exists to stop.
    """
    server = await repo.get_server(session, org_id, server_id)
    if server is None:
        raise ServerNotFoundError(str(server_id))

    requested = {item.value for item in payload.environments}
    beyond = requested - set(server.environments)
    if beyond:
        raise EnvironmentNotEnabledError(", ".join(sorted(beyond)))

    pinned: UUID | None = None
    if payload.pin_approved_snapshot:
        if server.approved_snapshot_id is None:
            raise NothingToApproveError(str(server_id))
        pinned = server.approved_snapshot_id

    row = await repo.insert_grant(
        session,
        org_id,
        {
            "server_id": server_id,
            "capability_name": payload.capability_name,
            "subject_kind": payload.subject_kind,
            "subject_id": payload.subject_id,
            "environments": sorted(requested),
            "permission": payload.permission,
            # This flag is an additional grant-level control. The server-wide write
            # policy is applied after resolving the concrete capability in ``decide``;
            # applying it here would incorrectly force approval on read-only tools.
            "requires_approval": payload.requires_approval,
            "pinned_snapshot_id": pinned,
            "granted_by": actor,
            "reason": payload.reason,
            "expires_at": payload.expires_at,
        },
    )
    return GrantOut.model_validate(row)


async def list_grants(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
) -> list[GrantOut]:
    rows = await repo.list_grants(session, org_id, server_id)
    return [GrantOut.model_validate(row) for row in rows]


async def revoke_grant(session: AsyncSession, org_id: UUID, grant_id: UUID) -> None:
    if not await repo.revoke_grant(session, org_id, grant_id):
        raise GrantNotFoundError(str(grant_id))


async def quarantine(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    payload: Quarantine,
) -> ServerOut:
    """Stop a server without unpicking its grants.

    Quarantine is the fast lever: one row, and ``decide`` denies everything for that
    server on the next call. Revoking grants one at a time is the slow, error-prone
    version of the same intent, and the state to restore afterwards is already recorded.
    """
    server = await repo.update_server(
        session,
        org_id,
        server_id,
        {
            "state": ServerState.QUARANTINED.value,
            "quarantined_at": datetime.now(UTC),
            "quarantine_reason": payload.reason,
        },
    )
    if server is None:
        raise ServerNotFoundError(str(server_id))
    return ServerOut.model_validate(server)


async def release(session: AsyncSession, org_id: UUID, server_id: UUID) -> ServerOut:
    """Lift a quarantine.

    The server returns to ``approved`` only if it still has an approved snapshot;
    otherwise it drops to ``in_review``, because letting it resume without one would
    mean every call is denied while the console claims the server is approved.
    """
    current = await repo.get_server(session, org_id, server_id)
    if current is None:
        raise ServerNotFoundError(str(server_id))

    state = (
        ServerState.APPROVED if current.approved_snapshot_id is not None else ServerState.IN_REVIEW
    )
    server = await repo.update_server(
        session,
        org_id,
        server_id,
        {
            "state": state.value,
            "quarantined_at": None,
            "quarantine_reason": None,
        },
    )
    if server is None:
        raise ServerNotFoundError(str(server_id))
    return ServerOut.model_validate(server)


async def decide(
    session: AsyncSession,
    org_id: UUID,
    *,
    server_slug: str,
    capability_name: str,
    subjects: list[tuple[str, UUID]],
    environment: str,
) -> ToolDecision:
    """Answer whether one tool call may proceed.

    Run before every MCP tool invocation, so it is deliberately one repository call and
    no I/O beyond it. Each denial carries a distinct ``reason_code`` because "blocked"
    with no cause is the thing that makes operators disable enforcement.

    The subject list comes from the verified workload credential, never from the request
    body: a caller must not be able to ask whether *somebody else* could make this call
    and then act on the answer.
    """
    server, capability, governing = await repo.decide_tool_call(
        session,
        org_id,
        server_slug=server_slug,
        capability_name=capability_name,
        subjects=subjects,
        environment=environment,
        now=datetime.now(UTC),
    )

    if server is None:
        return ToolDecision(
            allowed=False,
            requires_approval=False,
            reason_code="server_not_registered",
        )
    if server.state == ServerState.QUARANTINED.value:
        return ToolDecision(
            allowed=False,
            requires_approval=False,
            reason_code="server_quarantined",
            server_id=server.id,
            capability_name=capability_name,
        )
    if server.state != ServerState.APPROVED.value or server.approved_snapshot_id is None:
        return ToolDecision(
            allowed=False,
            requires_approval=False,
            reason_code="server_not_approved",
            server_id=server.id,
            capability_name=capability_name,
        )
    if environment not in server.environments:
        return ToolDecision(
            allowed=False,
            requires_approval=False,
            reason_code="environment_not_enabled",
            server_id=server.id,
            capability_name=capability_name,
        )
    if governing is None:
        return ToolDecision(
            allowed=False,
            requires_approval=False,
            reason_code="no_grant",
            server_id=server.id,
            capability_name=capability_name,
        )
    if capability is None:
        # There is a grant, but the tool is not in the snapshot that grant resolves
        # against. This is the rug-pull denial: the server grew a tool after approval.
        return ToolDecision(
            allowed=False,
            requires_approval=False,
            reason_code="capability_not_in_pinned_snapshot",
            server_id=server.id,
            capability_name=capability_name,
            grant_id=governing.id,
        )

    requires_approval = capability.verified_write and (
        governing.requires_approval or server.requires_approval_for_writes
    )
    return ToolDecision(
        allowed=True,
        requires_approval=requires_approval,
        reason_code="approval_required" if requires_approval else "granted",
        server_id=server.id,
        capability_name=capability.name,
        verified_risk=RiskTier(capability.verified_risk),
        verified_write=capability.verified_write,
        grant_id=governing.id,
        snapshot_digest_hex=None,
    )


async def ingest_usage(
    session: AsyncSession,
    org_id: UUID,
    rows: list[UsageIngest],
) -> int:
    """Merge a window of daily aggregates from the worker.

    Aggregates only. At billions of tool calls a day a per-call control-plane row is not
    an option; the per-call record lives in ClickHouse behind Observe and this is the
    rollup the console and the grant reviewer read.
    """
    return await repo.upsert_usage(
        session,
        org_id,
        [
            {
                "usage_date": date.fromisoformat(row.usage_date),
                "server_id": row.server_id,
                "capability_name": row.capability_name,
                "agent_id": row.agent_id or UNATTRIBUTED,
                "member_id": row.member_id or UNATTRIBUTED,
                "call_count": row.call_count,
                "denied_count": row.denied_count,
                "approval_count": row.approval_count,
                "error_count": row.error_count,
                "p95_latency_ms": row.p95_latency_ms,
                "cost_micros": row.cost_micros,
            }
            for row in rows
        ],
    )


async def usage(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    *,
    days: int = USAGE_WINDOW_DAYS,
) -> list[UsageRollup]:
    since = datetime.now(UTC).date() - timedelta(days=days)
    rows = await repo.usage_for_server(session, org_id, server_id, since=since)
    return [
        UsageRollup(
            usage_date=row.usage_date.isoformat(),
            server_id=row.server_id,
            capability_name=row.capability_name,
            call_count=row.call_count,
            denied_count=row.denied_count,
            approval_count=row.approval_count,
            error_count=row.error_count,
            p95_latency_ms=row.p95_latency_ms,
            cost_micros=row.cost_micros,
        )
        for row in rows
    ]


def dangerous(capability: CapabilityOut) -> bool:
    """Whether a capability needs a second pair of eyes before it is granted."""
    return capability.verified_irreversible or capability.verified_risk.value in _DANGEROUS_RISKS


__all__ = [
    "AlreadyApprovedError",
    "CapabilityNotFoundError",
    "DuplicateServerError",
    "EnvironmentNotEnabledError",
    "GrantNotFoundError",
    "McpRegistryError",
    "NothingToApproveError",
    "ServerNotFoundError",
    "SnapshotNotFoundError",
    "SnapshotNotOnServerError",
    "approve_snapshot",
    "capability_digest",
    "dangerous",
    "decide",
    "get_server",
    "grant",
    "ingest_usage",
    "list_grants",
    "list_servers",
    "quarantine",
    "register_server",
    "release",
    "review_capability",
    "revoke_grant",
    "server_detail",
    "submit_snapshot",
    "update_server",
    "usage",
]
