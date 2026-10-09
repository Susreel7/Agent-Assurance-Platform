"""Trust portal HTTP handlers."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.deps import Session, VerifiedOrg
from app.api.route import TransactionalRoute
from app.domains.portal import service
from app.domains.portal.schemas import PortalViewOut

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.EngagementNotFoundError: status.HTTP_404_NOT_FOUND,
}


# Both slugs are in the path because one does not identify an engagement: the uniqueness
# constraint is per customer, so `/portal/managed-ai-delivery` matched five clients at
# once in the seeded estate. The link a customer receives now names them (D-035).
@router.get("/{customer_slug}/{engagement_slug}", response_model=PortalViewOut)
async def get_portal_view(
    customer_slug: str,
    engagement_slug: str,
    session: Session,
    org_id: VerifiedOrg,
) -> PortalViewOut:
    try:
        return await service.build_portal_view_by_slug(
            session, org_id, customer_slug, engagement_slug
        )
    except service.PortalError as exc:
        code = _STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST)
        raise HTTPException(code, detail=str(exc)) from exc


@router.get("/{customer_slug}/{engagement_slug}/packs/{pack_id}")
async def get_pack_reference(
    customer_slug: str,
    engagement_slug: str,
    pack_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> dict[str, str]:
    try:
        uri = await service.get_pack_download(
            session, org_id, customer_slug, engagement_slug, pack_id
        )
    except service.PortalError as exc:
        code = _STATUS_FOR.get(type(exc), status.HTTP_404_NOT_FOUND)
        raise HTTPException(code, detail=str(exc)) from exc
    return {"pack_uri": uri}
