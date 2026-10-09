"""Version 1 router aggregation.

Domain routers are registered here explicitly rather than auto-discovered, so the whole
API surface is auditable by reading one file. That matters the first time a customer's
security team asks what endpoints exist — the answer should not require a code search.

The order below follows the six HLD layers bottom-up, matching the dependency direction
in AGENTS.md. Reading it top to bottom is reading the product.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.access import router as access_router
from app.domains.accreditation import router as accreditation_router
from app.domains.artifact_workspace import router as artifact_workspace_router
from app.domains.assurance import router as assurance_router
from app.domains.attestation import router as attestation_router
from app.domains.auth import router as auth_router
from app.domains.bom import router as bom_router
from app.domains.bootstrap import router as bootstrap_router
from app.domains.composition import router as composition_router
from app.domains.connections import router as connections_router
from app.domains.customers import router as customers_router
from app.domains.engagements import router as engagements_router
from app.domains.evaluation_workspace import router as evaluation_workspace_router
from app.domains.evidence import router as evidence_router
from app.domains.frameworks import router as frameworks_router
from app.domains.graph import router as graph_router
from app.domains.home import router as home_router
from app.domains.materiality import router as materiality_router
from app.domains.mcp_registry import router as mcp_registry_router
from app.domains.members import router as members_router
from app.domains.model_routing import router as model_routing_router
from app.domains.modules import router as modules_router
from app.domains.observe import router as observe_router
from app.domains.operations import router as operations_router
from app.domains.policy import router as policy_router
from app.domains.portal import router as portal_router
from app.domains.registry import router as registry_router
from app.domains.releases import router as releases_router
from app.domains.security_audit import router as security_audit_router
from app.domains.sla import router as sla_router
from app.domains.workload_identity import router as workload_identity_router

router = APIRouter()

# ---- Layer 0: who is asking, and what may they do ----
# First because every router below it is authorised by what these own. They are outside
# the domain layer chain (see app/domains/layer_order.py) for the same reason:
# authorisation is not a step in the pipeline, it is the condition on every step.
#
# `/auth` is first of the first: two of its endpoints answer without a credential, and
# they are how a caller acquires one. `/session/bootstrap` is next, because it is the
# single request the console shell renders from — see the invariant of the same name.
router.include_router(auth_router.router, prefix="/auth", tags=["auth"])
router.include_router(bootstrap_router.router, prefix="/session", tags=["session"])
router.include_router(members_router.router, prefix="/members", tags=["members"])
router.include_router(access_router.router, prefix="/access", tags=["access"])

# ---- Layer 3: the company model and the system of record ----
router.include_router(customers_router.router, prefix="/customers", tags=["customers"])
router.include_router(engagements_router.router, prefix="/engagements", tags=["engagements"])
router.include_router(frameworks_router.router, prefix="/frameworks", tags=["frameworks"])
router.include_router(registry_router.router, prefix="/agents", tags=["registry"])
router.include_router(
    workload_identity_router.router,
    prefix="/workload-credentials",
    tags=["workload-credentials"],
)
# Provider connections and the MCP registry sit here, directly after the agent registry:
# an MCP server is reached through a connection, and both are things an agent is granted
# rather than things it declares. Everything to the right may read them.
router.include_router(connections_router.router, prefix="/connections", tags=["connections"])
router.include_router(mcp_registry_router.router, prefix="/mcp", tags=["mcp-registry"])
router.include_router(releases_router.router, prefix="/releases", tags=["releases"])
router.include_router(bom_router.router, prefix="/bom", tags=["bom"])
router.include_router(composition_router.router, prefix="/agents", tags=["composition"])
# Runtime operations sits between the bill of materials and evidence: it reads both the
# registry and the BOM, and nothing to its left reads it. Everything before this point
# describes agents as declared; this is the first router that knows what they did.
router.include_router(operations_router.router, prefix="/operations", tags=["operations"])
router.include_router(observe_router.router, prefix="/observe", tags=["observe"])
router.include_router(
    artifact_workspace_router.router, prefix="/artifacts", tags=["artifact-workspace"]
)
router.include_router(
    evaluation_workspace_router, prefix="/evaluate", tags=["evaluation-workspace"]
)
router.include_router(evidence_router.router, prefix="/evidence", tags=["evidence"])
router.include_router(graph_router.router, prefix="/graph", tags=["graph"])

# ---- Layer 4: continuous evaluation ----
router.include_router(policy_router.router, prefix="/policies", tags=["policy"])
router.include_router(model_routing_router.router, prefix="/model-routing", tags=["model-routing"])
router.include_router(assurance_router.router, prefix="/assurance", tags=["assurance"])
router.include_router(sla_router.router, prefix="/slos", tags=["sla"])

# ---- Layer 5: accreditation and attestation ----
router.include_router(materiality_router.router, prefix="/materiality", tags=["materiality"])
router.include_router(accreditation_router.router, prefix="/accreditations", tags=["accreditation"])
router.include_router(attestation_router.router, prefix="/attestations", tags=["attestation"])

# ---- Layer 6: consumption ----
# Mounted under /portal and scoped to one engagement. The only router in the system a
# customer's own staff reach, so it is deliberately last and deliberately separate.
router.include_router(portal_router.router, prefix="/portal", tags=["portal"])

# The console's landing page. Last because it depends on everything above it and is
# depended on by nothing — it owns no tables and composes other domains' services.
router.include_router(home_router.router, prefix="/home", tags=["home"])
router.include_router(modules_router.router, prefix="/modules", tags=["modules"])

# The evidence trail for everything above. Mounted last because it is written by every
# layer and read by none of them — it has no dependents, only producers.
router.include_router(security_audit_router.router, prefix="/audit", tags=["security-audit"])


@router.get("/", include_in_schema=False)
async def index() -> dict[str, str]:
    return {"api": "v1", "docs": "/docs"}
