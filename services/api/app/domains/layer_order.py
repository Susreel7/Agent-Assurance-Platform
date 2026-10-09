"""Declared domain dependency order (AGENTS.md rule 3).

This tuple is the single source of truth for layering invariants. ``AGENTS.md`` must
stay aligned with it; ``tests/unit/test_domain_layer_order.py`` imports it directly so
the documented chain and the enforced graph cannot drift apart.
"""

from __future__ import annotations

DOMAIN_LAYER_ORDER: tuple[str, ...] = (
    "customers",
    "frameworks",
    "registry",
    # Provider connections sit directly after the registry: an MCP server may be reached
    # through one, and `model_routing` resolves a target's credential from one. Both are
    # to the right of it, so both may read it.
    "connections",
    "mcp_registry",
    "releases",
    "bom",
    "operations",
    "composition",
    "evidence",
    "engagements",
    "graph",
    "policy",
    "materiality",
    "accreditation",
    "assurance",
    "model_routing",
    "sla",
    "attestation",
    "portal",
)

# Cross-cutting domains that do not participate in the business dependency chain.
#
# `members`, `access` and `security_audit` are here for the same reason
# `workload_identity` is: they answer "who is this" and "what happened", which every
# layer needs. Placing them in the chain would force an ordering between authorization
# and the things it authorises, and there is no honest one.
#
# `auth` and `bootstrap` join them, one on each side of the request. `auth` runs before
# any layer — it is what decides whether there is a caller at all — and `bootstrap`
# composes several layers into the one response the console shell renders from. Neither
# is a step in the pipeline, so neither has a position in it.
DOMAINS_OUTSIDE_LAYER: frozenset[str] = frozenset(
    {
        "home",
        "modules",
        "observe",
        "workload_identity",
        "artifact_workspace",
        "evaluation_workspace",
        "auth",
        "bootstrap",
        "members",
        "access",
        "security_audit",
        # The action ledger sits beside `security_audit` for the same reason: it answers
        # "what happened", which every layer produces and none owns. Giving it a position
        # in the chain would force an ordering between the ledger and the capabilities it
        # records, and there is no honest one.
        "agent_actions",
    }
)

_LAYER_INDEX: dict[str, int] = {name: idx for idx, name in enumerate(DOMAIN_LAYER_ORDER)}


def layer_index(domain: str) -> int:
    try:
        return _LAYER_INDEX[domain]
    except KeyError as exc:
        raise ValueError(f"unknown domain {domain!r}") from exc


def may_import_domain(source: str, target: str) -> bool:
    """True when ``source`` may import ``target`` under rule 3 (leftward only)."""
    if source in DOMAINS_OUTSIDE_LAYER or target in DOMAINS_OUTSIDE_LAYER:
        return True
    if source not in _LAYER_INDEX or target not in _LAYER_INDEX:
        return True
    return layer_index(source) > layer_index(target)
