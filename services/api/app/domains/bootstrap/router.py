"""The shell's single identity request.

Mounted at `/v1/session/bootstrap` rather than under a domain prefix because it is not
about one domain — it is the answer to "who am I and what does this console look like for
me", which is the question every screen used to ask separately.

``inv_bootstrap_is_single_request`` asserts that loading the shell hits exactly one
identity-related endpoint. This is that endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Auth, CurrentMember, Session, VerifiedOrg, current_entitlement
from app.api.route import TransactionalRoute
from app.domains.bootstrap import service
from app.domains.bootstrap.schemas import BootstrapOut

router = APIRouter(route_class=TransactionalRoute)


@router.get(
    "/bootstrap",
    response_model=BootstrapOut,
    summary="Everything the console shell needs to render",
)
async def bootstrap(
    auth: Auth,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> BootstrapOut:
    entitlement = current_entitlement()
    return await service.bootstrap(
        session,
        org_id,
        member.member_id,
        console=auth.console,
        read_only=entitlement is not None and entitlement.read_only,
    )
