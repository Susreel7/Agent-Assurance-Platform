"""BOM business logic — extract, persist and query component dependencies."""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.bom import repository as repo
from app.domains.bom.schemas import BomComponentOut, BomPage, BomSummary, ComponentKind
from app.domains.registry import service as registry_svc
from app.domains.registry.service import AgentNotFoundError, VersionNotFoundError

_VECTOR_KINDS = frozenset({"vector_store", "vector", "pinecone", "weaviate", "qdrant"})


def _extract_composition_components(descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    """BOM rows from ``composition.*`` without importing the composition domain (D-011)."""
    rows: list[dict[str, Any]] = []
    block = descriptor.get("composition")
    if not isinstance(block, dict):
        return rows

    policy = block.get("model_policy")
    if isinstance(policy, dict) and policy.get("selection_mode"):
        rows.append(
            {
                "kind": ComponentKind.MODEL_POLICY.value,
                "name": str(policy.get("selection_mode")),
                "declared_meta": policy,
            }
        )

    for source in block.get("rule_sources") or []:
        if isinstance(source, dict) and source.get("name"):
            rows.append(
                {
                    "kind": ComponentKind.RULE_SOURCE.value,
                    "name": str(source["name"]),
                    "digest": source.get("digest"),
                    "declared_meta": {"path": source.get("path"), "kind": source.get("kind")},
                }
            )

    for obl in block.get("rule_obligations") or []:
        if isinstance(obl, dict) and obl.get("id"):
            rows.append(
                {
                    "kind": ComponentKind.RULE_OBLIGATION.value,
                    "name": str(obl["id"]),
                    "digest": obl.get("digest"),
                    "declared_meta": {"category": obl.get("category")},
                }
            )

    for section, kind in (
        ("skills", ComponentKind.SKILL),
        ("configs", ComponentKind.CONFIG),
        ("sub_agents", ComponentKind.SUB_AGENT),
    ):
        for item in block.get(section) or []:
            if isinstance(item, dict) and item.get("name"):
                rows.append(
                    {
                        "kind": kind.value,
                        "name": str(item["name"]),
                        "digest": item.get("digest"),
                        "declared_meta": {"path": item.get("path"), "ref": item.get("ref")},
                    }
                )

    for item in block.get("memory_retrieval") or []:
        if isinstance(item, dict) and item.get("name"):
            rows.append(
                {
                    "kind": ComponentKind.DATA_SOURCE.value,
                    "name": str(item["name"]),
                    "declared_meta": item,
                }
            )

    for item in block.get("guardrails") or []:
        if isinstance(item, dict) and item.get("name"):
            rows.append(
                {
                    "kind": ComponentKind.GUARDRAIL.value,
                    "name": str(item["name"]),
                    "digest": item.get("digest"),
                }
            )

    return rows


class BomError(Exception):
    """Base for everything this module raises."""


class BomVersionNotFoundError(BomError):
    def __init__(self, version_id: UUID) -> None:
        super().__init__(f"version {version_id} not found")
        self.version_id = version_id


class BomAgentNotFoundError(BomError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"agent {agent_id} not found")
        self.agent_id = agent_id


def extract_components(descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure extraction from an AAP descriptor. No I/O, easy to unit test."""
    rows: list[dict[str, Any]] = []

    for model in descriptor.get("models") or []:
        if not isinstance(model, dict):
            continue
        provider = str(model.get("provider", "unknown"))
        family = str(model.get("family", "unknown"))
        ident = str(model.get("id") or model.get("family") or "unknown")
        role = str(model.get("role", "primary"))
        rows.append(
            {
                "kind": ComponentKind.MODEL.value,
                "name": f"{provider}/{family}/{ident}",
                "version": role,
                "provider": provider,
                "declared_meta": {"role": role, "hosting": model.get("hosting")},
            }
        )

    for prompt in descriptor.get("prompts") or []:
        if not isinstance(prompt, dict) or not prompt.get("name"):
            continue
        rows.append(
            {
                "kind": ComponentKind.PROMPT.value,
                "name": str(prompt["name"]),
                "digest": prompt.get("digest"),
                "declared_meta": {"role": prompt.get("role")},
            }
        )

    for tool in descriptor.get("tools") or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        rows.append(
            {
                "kind": ComponentKind.TOOL.value,
                "name": str(tool["name"]),
                "effect": tool.get("effect"),
                "reversible": tool.get("reversible"),
                "declared_meta": {"kind": tool.get("kind"), "endpoint": tool.get("endpoint")},
            }
        )

    for server in (descriptor.get("references") or {}).get("mcp_servers") or []:
        if not isinstance(server, dict) or not server.get("url"):
            continue
        rows.append(
            {
                "kind": ComponentKind.MCP_SERVER.value,
                "name": str(server["url"]),
                "digest": server.get("digest"),
            }
        )

    for source in (descriptor.get("data") or {}).get("sources") or []:
        if not isinstance(source, dict) or not source.get("name"):
            continue
        kind_raw = str(source.get("kind", "data_source")).lower()
        kind = (
            ComponentKind.VECTOR_STORE.value
            if kind_raw in _VECTOR_KINDS
            else ComponentKind.DATA_SOURCE.value
        )
        rows.append(
            {
                "kind": kind,
                "name": str(source["name"]),
                "declared_meta": {"region": source.get("region"), "kind": source.get("kind")},
            }
        )

    for delegate in descriptor.get("delegates_to") or []:
        if not isinstance(delegate, dict) or not delegate.get("urn"):
            continue
        rows.append(
            {
                "kind": ComponentKind.SUB_AGENT.value,
                "name": str(delegate["urn"]),
                "declared_meta": {
                    "trust": delegate.get("trust"),
                    "protocol": delegate.get("protocol"),
                },
            }
        )

    for defence in (descriptor.get("security") or {}).get("prompt_injection_defences") or []:
        rows.append(
            {
                "kind": ComponentKind.GUARDRAIL.value,
                "name": str(defence),
            }
        )

    rows.extend(_extract_composition_components(descriptor))

    return rows


async def component_counts_by_agent(
    session: AsyncSession, org_id: UUID
) -> dict[UUID, dict[str, int]]:
    """Per agent, how many MCP servers and tools its live version declares.

    Returned for every agent at once because the caller is rendering a table. Anything
    not declared is absent from the result rather than zero, so callers supply their own
    default and an agent with no bill of materials is distinguishable from one with an
    empty one only by looking, which is the honest state of affairs.
    """
    counts: dict[UUID, dict[str, int]] = {}
    for row in await repo.count_by_agent_and_kind(session, org_id):
        bucket = counts.setdefault(row.agent_id, {"mcp_servers": 0, "tools": 0})
        if row.kind == ComponentKind.MCP_SERVER.value:
            bucket["mcp_servers"] += int(row.components)
        elif row.kind == ComponentKind.TOOL.value:
            bucket["tools"] += int(row.components)
    return counts


def summarise_bom(agent_version_id: UUID, components: list[BomComponentOut]) -> BomSummary:
    counts = Counter(c.kind.value for c in components)
    return BomSummary(
        agent_version_id=agent_version_id,
        total=len(components),
        by_kind=dict(counts),
    )


async def persist_components(
    session: AsyncSession, org_id: UUID, agent_version_id: UUID, descriptor: dict[str, Any]
) -> BomPage:
    extracted = extract_components(descriptor)
    rows = [
        {
            "agent_version_id": agent_version_id,
            "kind": row["kind"],
            "name": row["name"],
            "version": row.get("version"),
            "provider": row.get("provider"),
            "effect": row.get("effect"),
            "reversible": row.get("reversible"),
            "digest": row.get("digest"),
            "declared_meta": row.get("declared_meta", {}),
        }
        for row in extracted
    ]
    await repo.insert_components(session, org_id, rows)
    return await get_bom_for_version(session, org_id, agent_version_id)


async def get_bom_for_version(
    session: AsyncSession, org_id: UUID, agent_version_id: UUID
) -> BomPage:
    stored = await repo.list_components(session, org_id, agent_version_id)
    items = [BomComponentOut.model_validate(c) for c in stored]
    summary = summarise_bom(agent_version_id, items)
    return BomPage(items=items, summary=summary)


async def get_bom_for_agent(session: AsyncSession, org_id: UUID, agent_id: UUID) -> BomPage:
    try:
        detail = await registry_svc.get_agent_detail(session, org_id, agent_id)
    except AgentNotFoundError as exc:
        raise BomAgentNotFoundError(agent_id) from exc
    if detail.current_version_id is None:
        raise BomError("agent has no published version yet")
    return await get_bom_for_version(session, org_id, detail.current_version_id)


async def get_bom(
    session: AsyncSession,
    org_id: UUID,
    *,
    agent_id: UUID | None = None,
    version_id: UUID | None = None,
) -> BomPage:
    if version_id is not None:
        try:
            await registry_svc.get_version_descriptor(session, org_id, version_id)
        except VersionNotFoundError as exc:
            raise BomVersionNotFoundError(version_id) from exc
        return await get_bom_for_version(session, org_id, version_id)
    if agent_id is not None:
        return await get_bom_for_agent(session, org_id, agent_id)
    raise BomError("agent_id or version_id is required")


async def find_agents_using(
    session: AsyncSession, org_id: UUID, kind: ComponentKind, name: str
) -> list[dict[str, Any]]:
    rows = await repo.fetch_usage(session, org_id, kind.value, name)
    return [
        {
            "agent_id": row.agent_id,
            "urn": row.urn,
            "version_id": row.version_id,
            "semver": row.semver,
            "kind": row.kind,
            "name": row.name,
        }
        for row in rows
    ]
