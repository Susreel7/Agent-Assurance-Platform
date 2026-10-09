"""Operations HTTP handlers. Thin by rule — every one delegates immediately.

`POST /runs` is the only write in this domain and the only endpoint an agent itself
calls. It is deliberately *not* behind the write guard: a lapsed licence degrades the
product to read-only, and dropping telemetry is the wrong way to chase an invoice. The
same reasoning already exempts evidence ingest.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    CollectorAuth,
    Session,
    VerifiedOrg,
    WorkloadSession,
    enforce_collector,
)
from app.api.route import TransactionalRoute
from app.domains.operations import service
from app.domains.operations.schemas import (
    ActivitySeries,
    AgentOperations,
    CostReport,
    FrameworkShare,
    IngestResult,
    McpInventory,
    ObservedGraph,
    OperationsSnapshot,
    RunBatch,
    RunDetail,
    RunOutcome,
    RunPage,
    ToolInventory,
)
from app.domains.registry.schemas import LifecycleState

router = APIRouter(route_class=TransactionalRoute)

Days = Annotated[int, Query(ge=1, le=service.MAX_WINDOW_DAYS)]


@router.post(
    "/runs",
    response_model=IngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Report agent runs — open them, then close them",
)
async def report_runs(
    payload: RunBatch,
    session: WorkloadSession,
    collector: CollectorAuth,
) -> IngestResult:
    """202 rather than 201. The batch may contain both new runs and updates to existing
    ones, so there is no single resource to point a Location header at."""
    workload = enforce_collector(collector, scope="ingest:runs", module="observe")
    try:
        return await service.record_runs(
            session,
            workload.org_id,
            payload,
            reporter_agent_id=workload.agent_id,
            reporter_environment=workload.environment.value,
            reporter_ref=service.workload_reporter_ref(workload.credential_id),
        )
    except service.UnknownAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except service.ReporterScopeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get(
    "/runs/{run_id}",
    response_model=RunDetail,
    summary="One run with its step trace",
)
async def run_detail(run_id: UUID, session: Session, org_id: VerifiedOrg) -> RunDetail:
    try:
        return await service.build_run_detail(session, org_id, run_id)
    except service.RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runs", response_model=RunPage, summary="List runs, newest first")
async def list_runs(
    session: Session,
    org_id: VerifiedOrg,
    days: Days = service.DEFAULT_WINDOW_DAYS,
    agent_id: UUID | None = None,
    environment: LifecycleState | None = None,
    outcome: Annotated[list[RunOutcome] | None, Query()] = None,
    escalated: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunPage:
    return await service.list_runs(
        session,
        org_id,
        days=days,
        agent_id=agent_id,
        environment=environment.value if environment else None,
        outcomes=[o.value for o in outcome] if outcome else None,
        escalated_only=escalated,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/overview",
    response_model=OperationsSnapshot,
    summary="Everything operations knows about the window",
)
async def overview(
    session: Session, org_id: VerifiedOrg, days: Days = service.DEFAULT_WINDOW_DAYS
) -> OperationsSnapshot:
    return await service.build_snapshot(session, org_id, days)


@router.get("/activity", response_model=ActivitySeries, summary="Runs per day per environment")
async def activity(
    session: Session, org_id: VerifiedOrg, days: Days = service.DEFAULT_WINDOW_DAYS
) -> ActivitySeries:
    return await service.build_activity_series(session, org_id, days)


@router.get(
    "/cost", response_model=CostReport, summary="Spend by day, model, agent and environment"
)
async def cost(
    session: Session, org_id: VerifiedOrg, days: Days = service.DEFAULT_WINDOW_DAYS
) -> CostReport:
    return await service.build_cost_report(session, org_id, days)


@router.get(
    "/tools",
    response_model=ToolInventory,
    summary="Tools and MCP servers called, and whether any descriptor declares them",
)
async def tools(
    session: Session, org_id: VerifiedOrg, days: Days = service.DEFAULT_WINDOW_DAYS
) -> ToolInventory:
    return await service.build_tool_inventory(session, org_id, days)


@router.get(
    "/mcp-servers",
    response_model=McpInventory,
    summary="MCP servers the estate called, and whether each caller declared them",
)
async def mcp_servers(
    session: Session,
    org_id: VerifiedOrg,
    days: Days = service.DEFAULT_WINDOW_DAYS,
    agent_id: UUID | None = None,
) -> McpInventory:
    return await service.build_mcp_inventory(session, org_id, days, agent_id=agent_id)


@router.get(
    "/agents/{agent_id}/graph",
    response_model=ObservedGraph,
    summary="LangGraph topology as observed from node steps",
)
async def observed_graph(
    agent_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    days: Days = service.DEFAULT_WINDOW_DAYS,
) -> ObservedGraph:
    """No 404 for an agent with no runs — an empty graph is the honest answer."""
    return await service.build_observed_graph(session, org_id, agent_id, days)


@router.get(
    "/agents/{agent_id}",
    response_model=AgentOperations,
    summary="Runs, cost, tools and MCP servers for one agent",
)
async def agent_operations(
    agent_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    days: Days = service.DEFAULT_WINDOW_DAYS,
) -> AgentOperations:
    """No 404 for an agent with no runs.

    An agent that has never run is a real and common state — it was registered this
    morning — and an empty window is the honest answer to "what has it been doing". A
    404 here would make the console's activity tab fail for exactly the agents somebody
    is most likely to be checking on.
    """
    return await service.build_agent_operations(session, org_id, agent_id, days)


@router.get(
    "/runtime-frameworks",
    response_model=list[FrameworkShare],
    summary="Share of the estate by agent framework — LangGraph, CrewAI, Cursor SDK",
)
async def runtime_frameworks(
    session: Session, org_id: VerifiedOrg, days: Days = service.DEFAULT_WINDOW_DAYS
) -> list[FrameworkShare]:
    """`runtime-frameworks`, not `frameworks`. `/v1/frameworks` is already the compliance
    control catalogue — ISO 42001, the EU AI Act — and one path meaning both would be a
    permanent source of confusion. The column behind this is
    `agent_versions.runtime_framework`, so the name matches the schema."""
    return await service.build_framework_shares(session, org_id, days)
