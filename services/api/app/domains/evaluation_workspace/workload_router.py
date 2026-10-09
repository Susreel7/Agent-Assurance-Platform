"""Machine-authenticated evaluate ingest — no human session headers."""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import CollectorAuth, WorkloadSession, enforce_collector
from app.api.route import TransactionalRoute
from app.domains.evaluation_workspace import service
from app.domains.evaluation_workspace.schemas import ScoreCreate, ScoreOut

router = APIRouter(route_class=TransactionalRoute)


def _raise_evaluate(exc: Exception) -> NoReturn:
    if isinstance(exc, service.EvaluateRequestError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(status_code=503, detail="Evaluate workspace service unavailable") from exc


@router.post(
    "/workload/scores",
    response_model=ScoreOut,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest an evaluation score with a workload credential",
)
async def create_workload_score(
    payload: ScoreCreate,
    session: WorkloadSession,
    collector: CollectorAuth,
    authorization: Annotated[str, Header(alias="Authorization")],
) -> ScoreOut:
    _ = session
    workload = enforce_collector(collector, scope="evaluate:score", module="evaluate")
    try:
        return await service.create_workload_score(
            workload.org_id,
            workload.project_id,
            authorization=authorization,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)
