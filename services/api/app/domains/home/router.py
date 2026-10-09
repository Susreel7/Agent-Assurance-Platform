"""Landing page handler."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import Session, VerifiedOrg
from app.api.route import TransactionalRoute
from app.domains.home import service
from app.domains.home.schemas import HomeSummary

router = APIRouter(route_class=TransactionalRoute)


@router.get(
    "/summary", response_model=HomeSummary, summary="Everything the console's home page shows"
)
async def home_summary(
    session: Session,
    org_id: VerifiedOrg,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> HomeSummary:
    return await service.build_home_summary(session, org_id, days)
