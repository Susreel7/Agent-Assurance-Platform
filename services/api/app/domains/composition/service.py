"""Composition — parse declarations, sync obligations, reconcile with runtime observation."""

from __future__ import annotations

import fnmatch
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.composition import repository as repo
from app.domains.composition.schemas import (
    CompositionBlock,
    CompositionElementKind,
    CompositionElementOut,
    CompositionSummary,
    ReconciliationPage,
    ReconciliationRowOut,
    ReconciliationStatus,
    RuleObligationIn,
)
from app.domains.operations import service as operations_svc
from app.domains.registry import service as registry_svc
from app.domains.registry.service import AgentNotFoundError, VersionNotFoundError

DEFAULT_WINDOW_DAYS = 7


class CompositionError(Exception):
    pass


class CompositionAgentNotFoundError(CompositionError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"agent {agent_id} not found")
        self.agent_id = agent_id


class CompositionVersionNotFoundError(CompositionError):
    def __init__(self, version_id: UUID) -> None:
        super().__init__(f"version {version_id} not found")
        self.version_id = version_id


def parse_composition_block(descriptor: dict[str, Any]) -> CompositionBlock | None:
    raw = descriptor.get("composition")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CompositionError("composition must be an object")
    try:
        block = CompositionBlock.model_validate(raw)
    except ValidationError as exc:
        raise CompositionError(f"invalid composition block: {exc}") from exc
    _require_stable_identities(raw)
    return block


def _require_stable_identities(raw: dict[str, Any]) -> None:
    """Lists diff by identity, not index — every element needs a stable key field."""
    checks: list[tuple[str, str]] = [
        ("rule_sources", "name"),
        ("skills", "name"),
        ("sub_agents", "name"),
        ("configs", "name"),
        ("memory_retrieval", "name"),
        ("guardrails", "name"),
    ]
    for section, field in checks:
        items = raw.get(section) or []
        if not isinstance(items, list):
            raise CompositionError(f"composition.{section} must be an array")
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise CompositionError(f"composition.{section} entries must be objects")
            key = item.get(field)
            if not isinstance(key, str) or not key.strip():
                raise CompositionError(f"composition.{section}[].{field} is required")
            if key in seen:
                raise CompositionError(f"duplicate {field} {key!r} in composition.{section}")
            seen.add(key)
    obligations = raw.get("rule_obligations") or []
    if obligations and not isinstance(obligations, list):
        raise CompositionError("composition.rule_obligations must be an array")
    ob_seen: set[str] = set()
    for item in obligations:
        if not isinstance(item, dict):
            raise CompositionError("composition.rule_obligations entries must be objects")
        oid = item.get("id")
        if not isinstance(oid, str) or not oid.strip():
            raise CompositionError("composition.rule_obligations[].id is required")
        if oid in ob_seen:
            raise CompositionError(f"duplicate obligation id {oid!r}")
        ob_seen.add(oid)


def validate_descriptor_composition(descriptor: dict[str, Any]) -> None:
    """Raises CompositionError when the optional composition block is malformed."""
    block = parse_composition_block(descriptor)
    if block is None:
        return
    for obl in block.rule_obligations:
        RuleObligationIn.model_validate(obl.model_dump())


def obligation_rows_from_descriptor(
    agent_version_id: UUID, block: CompositionBlock
) -> list[dict[str, Any]]:
    return [
        {
            "agent_version_id": agent_version_id,
            "obligation_id": obl.id,
            "source_ref": obl.source_ref,
            "category": obl.category,
            "polarity": obl.polarity,
            "strength": obl.strength,
            "statement": obl.statement,
            "digest": obl.digest,
        }
        for obl in block.rule_obligations
    ]


def _declared_tools(descriptor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for tool in descriptor.get("tools") or []:
        if isinstance(tool, dict) and tool.get("name"):
            out[str(tool["name"]).strip().lower()] = dict(tool)
    return out


def _declared_mcp_keys(descriptor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for server in (descriptor.get("references") or {}).get("mcp_servers") or []:
        if not isinstance(server, dict):
            continue
        url = server.get("url")
        if not isinstance(url, str):
            continue
        name = server.get("name")
        meta = dict(server)
        for key in operations_svc.declaration_keys(url):
            out[key] = meta
        if isinstance(name, str) and name.strip():
            out[name.strip().lower()] = meta
    return out


def declared_model_keys(descriptor: dict[str, Any]) -> set[str]:
    """Model ids and allowlist patterns declared on a descriptor (incl. composition policy)."""
    keys: set[str] = set()
    for model in descriptor.get("models") or []:
        if not isinstance(model, dict):
            continue
        provider = str(model.get("provider", "")).strip().lower()
        ident = str(model.get("id") or model.get("family") or "").strip().lower()
        if ident:
            keys.add(ident)
            if provider:
                keys.add(f"{provider}/{ident}")
    block = descriptor.get("composition") or {}
    policy = block.get("model_policy") if isinstance(block, dict) else None
    if isinstance(policy, dict):
        pin = policy.get("pin") or {}
        if isinstance(pin, dict):
            pid = pin.get("id")
            if isinstance(pid, str) and pid.strip():
                keys.add(pid.strip().lower())
        for pattern in policy.get("allowlist") or []:
            if isinstance(pattern, str) and pattern.strip():
                keys.add(pattern.strip().lower())
    return keys


def model_allowed(observed: str, declared: set[str]) -> bool:
    """Whether an observed model id matches declared pins or allowlist patterns."""
    obs = observed.strip().lower()
    if obs in declared:
        return True
    for pattern in declared:
        if ("*" in pattern or "?" in pattern) and fnmatch.fnmatchcase(obs, pattern):
            return True
        if obs.endswith(pattern) or pattern.endswith(obs):
            return True
    return False


def _named_section(
    block: CompositionBlock | None,
    attr: str,
    kind: CompositionElementKind,
) -> dict[str, dict[str, Any]]:
    if block is None:
        return {}
    items: list[dict[str, Any]] = getattr(block, attr) or []
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            out[name.strip().lower()] = item
    return out


def _status(declared: bool, observed: bool, *, conflict: bool = False) -> ReconciliationStatus:
    if conflict:
        return ReconciliationStatus.CONFLICT
    if declared and observed:
        return ReconciliationStatus.ALIGNED
    if declared:
        return ReconciliationStatus.DECLARED_ONLY
    if observed:
        return ReconciliationStatus.OBSERVED_ONLY
    return ReconciliationStatus.ALIGNED


def build_element_view(
    descriptor: dict[str, Any],
    observed: dict[tuple[CompositionElementKind, str], int],
) -> list[CompositionElementOut]:
    """Merge declared composition with observed counts for the console."""
    block = parse_composition_block(descriptor)
    elements: list[CompositionElementOut] = []

    declared_tools = _declared_tools(descriptor)
    all_tool_keys = set(declared_tools) | {
        k for (kind, k) in observed if kind == CompositionElementKind.TOOL
    }
    for key in sorted(all_tool_keys):
        obs = observed.get((CompositionElementKind.TOOL, key), 0)
        decl = key in declared_tools
        elements.append(
            CompositionElementOut(
                kind=CompositionElementKind.TOOL,
                key=key,
                declared=decl,
                observed=obs > 0,
                status=_status(decl, obs > 0),
                observed_count=obs,
                declared_meta=declared_tools.get(key, {}),
            )
        )

    declared_mcp = _declared_mcp_keys(descriptor)
    mcp_observed: dict[str, int] = {}
    for (kind, key), count in observed.items():
        if kind != CompositionElementKind.MCP_SERVER:
            continue
        mcp_observed[key] = mcp_observed.get(key, 0) + count

    mcp_keys = set(mcp_observed)
    for key in declared_mcp:
        mcp_keys.update(operations_svc.declaration_keys(key))

    for key in sorted(mcp_keys):
        obs = mcp_observed.get(key, 0)
        keys = operations_svc.declaration_keys(key)
        decl = bool(declared_mcp.keys() & keys) or key in declared_mcp
        elements.append(
            CompositionElementOut(
                kind=CompositionElementKind.MCP_SERVER,
                key=key,
                declared=decl,
                observed=obs > 0,
                status=_status(decl, obs > 0),
                observed_count=obs,
            )
        )

    declared_models = declared_model_keys(descriptor)
    model_obs: dict[str, int] = {}
    for (kind, key), count in observed.items():
        if kind == CompositionElementKind.MODEL:
            model_obs[key] = model_obs.get(key, 0) + count
    for key in sorted(set(declared_models) | set(model_obs)):
        obs = model_obs.get(key, 0)
        decl = key in declared_models or any(
            fnmatch.fnmatchcase(key, p) for p in declared_models if "*" in p
        )
        conflict = obs > 0 and not model_allowed(key, declared_models)
        elements.append(
            CompositionElementOut(
                kind=CompositionElementKind.MODEL,
                key=key,
                declared=decl,
                observed=obs > 0,
                status=_status(decl, obs > 0, conflict=conflict),
                observed_count=obs,
            )
        )

    section_map: list[tuple[str, CompositionElementKind]] = [
        ("skills", CompositionElementKind.SKILL),
        ("sub_agents", CompositionElementKind.SUB_AGENT),
        ("configs", CompositionElementKind.CONFIG),
        ("memory_retrieval", CompositionElementKind.MEMORY_RETRIEVAL),
        ("guardrails", CompositionElementKind.GUARDRAIL),
    ]
    for attr, kind in section_map:
        declared = _named_section(block, attr, kind)
        obs_keys = {k for (knd, k) in observed if knd == kind}
        for key in sorted(set(declared) | obs_keys):
            obs = observed.get((kind, key), 0)
            decl = key in declared
            elements.append(
                CompositionElementOut(
                    kind=kind,
                    key=key,
                    declared=decl,
                    observed=obs > 0,
                    status=_status(decl, obs > 0),
                    observed_count=obs,
                    declared_meta=declared.get(key, {}),
                )
            )

    if block:
        for obl in block.rule_obligations:
            key = obl.id.strip().lower()
            elements.append(
                CompositionElementOut(
                    kind=CompositionElementKind.RULE_OBLIGATION,
                    key=key,
                    declared=True,
                    observed=False,
                    status=ReconciliationStatus.DECLARED_ONLY,
                    declared_meta={"statement": obl.statement, "category": obl.category},
                )
            )

    return elements


async def sync_obligations_from_descriptor(
    session: AsyncSession,
    org_id: UUID,
    agent_version_id: UUID,
    descriptor: dict[str, Any],
) -> None:
    block = parse_composition_block(descriptor)
    rows = obligation_rows_from_descriptor(agent_version_id, block) if block else []
    await repo.replace_obligations(session, org_id, agent_version_id, rows)


async def collect_observed(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    window_days: int,
) -> dict[tuple[CompositionElementKind, str], int]:
    window_days = max(1, min(window_days, 90))
    since = datetime.now(tz=UTC) - timedelta(days=window_days)
    since_day = since.date()
    observed: dict[tuple[CompositionElementKind, str], int] = {}

    for row in await repo.observed_tool_counts(session, org_id, agent_id, since_day):
        key = str(row.name).strip().lower()
        observed[(CompositionElementKind.TOOL, key)] = int(row.calls or 0)

    for row in await repo.observed_mcp_counts(session, org_id, agent_id, since_day):
        key = str(row.name).strip().lower()
        observed[(CompositionElementKind.MCP_SERVER, key)] = int(row.calls or 0)

    for row in await repo.observed_step_counts(session, org_id, agent_id, since, kind="llm"):
        model = row.model or row.name
        if isinstance(model, str) and model.strip():
            key = model.strip().lower()
            observed[(CompositionElementKind.MODEL, key)] = observed.get(
                (CompositionElementKind.MODEL, key), 0
            ) + int(row.calls or 0)

    for kind, el_kind in (
        ("tool", CompositionElementKind.TOOL),
        ("mcp_tool", CompositionElementKind.MCP_SERVER),
        ("sub_agent", CompositionElementKind.SUB_AGENT),
        ("retrieval", CompositionElementKind.MEMORY_RETRIEVAL),
        ("guardrail", CompositionElementKind.GUARDRAIL),
    ):
        for row in await repo.observed_step_counts(session, org_id, agent_id, since, kind=kind):
            if kind == "mcp_tool" and row.server_name:
                key = str(row.server_name).strip().lower()
                el = CompositionElementKind.MCP_SERVER
            elif kind == "llm":
                continue
            else:
                key = str(row.name).strip().lower()
                el = el_kind
            observed[(el, key)] = observed.get((el, key), 0) + int(row.calls or 0)

    return observed


async def reconcile_agent(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    version_id: UUID | None = None,
) -> ReconciliationPage:
    try:
        detail = await registry_svc.get_agent_detail(session, org_id, agent_id)
    except AgentNotFoundError as exc:
        raise CompositionAgentNotFoundError(agent_id) from exc

    target_version = version_id or detail.current_version_id
    if target_version is None:
        raise CompositionError("agent has no published version")

    descriptor = await registry_svc.get_version_descriptor(session, org_id, target_version)
    await sync_obligations_from_descriptor(session, org_id, target_version, descriptor)

    observed = await collect_observed(session, org_id, agent_id, window_days)
    elements = build_element_view(descriptor, observed)

    window_end = datetime.now(tz=UTC).date()
    window_start = window_end - timedelta(days=window_days)
    now = datetime.now(tz=UTC)

    rows: list[dict[str, Any]] = []
    for el in elements:
        rows.append(
            {
                "agent_id": agent_id,
                "agent_version_id": target_version,
                "element_kind": el.kind.value,
                "element_key": el.key,
                "declared": el.declared,
                "observed": el.observed,
                "status": el.status.value,
                "observed_count": el.observed_count,
                "window_start": window_start,
                "window_end": window_end,
                "computed_at": now,
            }
        )
    await repo.upsert_reconciliations(session, org_id, rows)

    stored = await repo.list_reconciliations(session, org_id, agent_id, window_end=window_end)
    return ReconciliationPage(
        agent_id=agent_id,
        agent_version_id=target_version,
        window_days=window_days,
        window_start=window_start,
        window_end=window_end,
        items=[ReconciliationRowOut.model_validate(r) for r in stored],
        elements=elements,
    )


async def get_composition_summary(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    version_id: UUID,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> CompositionSummary:
    try:
        version = await registry_svc.get_agent_version(session, org_id, agent_id, version_id)
    except (AgentNotFoundError, VersionNotFoundError) as exc:
        if isinstance(exc, AgentNotFoundError):
            raise CompositionAgentNotFoundError(agent_id) from exc
        raise CompositionVersionNotFoundError(version_id) from exc

    descriptor = await registry_svc.get_version_descriptor(session, org_id, version_id)
    block = parse_composition_block(descriptor)
    observed = await collect_observed(session, org_id, agent_id, window_days)
    elements = build_element_view(descriptor, observed)

    return CompositionSummary(
        agent_id=agent_id,
        agent_version_id=version_id,
        semver=version.semver,
        elements=elements,
        rule_sources=list(block.rule_sources) if block else [],
        rule_obligations=list(block.rule_obligations) if block else [],
        model_policy=block.model_policy if block else None,
    )
