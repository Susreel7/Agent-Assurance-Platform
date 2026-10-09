"""Model routing — compile obligations, evaluate pre-dispatch, emit gateway config, detect drift.

We sit upstream of the AI gateway (L7 proxies like Envoy handle TLS and rate limits; the
gateway understands models, regions and spend). Our job is to be the *policy authority*:
compile an agent's engagement terms and descriptor ``composition.model_policy`` into
configuration a gateway can enforce, record immutable ``policy_decisions`` when we deny,
and compare gateway logs and ``run_steps.model`` to catch bypass or stale config.

Catalogue ``primary_region`` and ``jurisdiction`` are *operator assertions*, not
cryptographic proof — a vendor can sub-route inside its estate and we only partially
observe that via response headers and post-hoc telemetry.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.assurance import service as assurance_svc
from app.domains.assurance.schemas import (
    FindingCategory,
    FindingCreate,
    FindingSource,
    Severity,
)
from app.domains.composition import service as composition_svc
from app.domains.engagements.schemas import CrossBorderTransfer
from app.domains.model_routing import repository as repo
from app.domains.model_routing.schemas import (
    AllowedDeployment,
    CatalogEntryCreate,
    CatalogEntryOut,
    CatalogPage,
    ClassificationState,
    CompiledModelPolicy,
    EnforcementLevel,
    GatewayConfigOut,
    GatewayLogIngest,
    GatewayTargetKind,
    ModelRoutingEvaluateRequest,
    ModelRoutingEvaluateResult,
    ModelSelectionMode,
    RoutingOverview,
)
from app.domains.operations import service as operations_svc
from app.domains.policy import service as policy_svc
from app.domains.policy.schemas import DecisionOutcome
from app.domains.registry import service as registry_svc
from app.domains.registry.schemas import LifecycleState

# Same ordering as ``_CROSS_BORDER_LADDER`` in materiality — engagement enum documents it.
_CROSS_BORDER_ORDER: tuple[CrossBorderTransfer, ...] = (
    CrossBorderTransfer.PROHIBITED,
    CrossBorderTransfer.PERMITTED_WITH_SAFEGUARDS,
    CrossBorderTransfer.PERMITTED_WITH_CONSENT,
    CrossBorderTransfer.PERMITTED,
)

_SAFEGUARD_BASES = frozenset(
    {
        "gdpr_art_46",
        "scc",
        "bcr",
        "adequacy",
        "binding_corporate_rules",
        "standard_contractual_clauses",
    }
)

_PRODUCTION_ENVIRONMENTS = frozenset(
    {LifecycleState.PRODUCTION.value, LifecycleState.STAGING.value}
)


class ModelRoutingError(Exception):
    """Base for everything this module raises."""


class AgentContextError(ModelRoutingError):
    pass


class CatalogEntryNotFoundError(ModelRoutingError):
    pass


def catalog_entry_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _region_prefix(region: str) -> str:
    upper = region.upper()
    if upper in {"GB", "EU"}:
        return region.lower()
    if "-" in region:
        return region.split("-", 1)[0].lower()
    return region.lower()


def _jurisdiction_from_region(region: str) -> str:
    prefix = _region_prefix(region)
    if prefix in {"eu", "europe"}:
        return "EU"
    if prefix == "us":
        return "US"
    if prefix == "gb":
        return "GB"
    return prefix.upper()


def _cross_border_index(rung: CrossBorderTransfer) -> int:
    return _CROSS_BORDER_ORDER.index(rung)


def cross_border_permits(
    engagement_rung: CrossBorderTransfer,
    *,
    descriptor_basis: str | None,
    lawful_basis_present: bool,
    home_jurisdictions: frozenset[str],
    model_jurisdiction: str,
) -> tuple[bool, str]:
    """Apply engagement cross-border ladder rungs to a model outside home jurisdictions."""
    if model_jurisdiction.upper() in {j.upper() for j in home_jurisdictions}:
        return True, "same_jurisdiction"

    if engagement_rung is CrossBorderTransfer.PROHIBITED:
        return False, "cross_border_prohibited"

    if engagement_rung is CrossBorderTransfer.PERMITTED_WITH_SAFEGUARDS:
        basis = (descriptor_basis or "").lower().replace("-", "_")
        if basis in _SAFEGUARD_BASES:
            return True, "cross_border_safeguards"
        return False, "cross_border_safeguards_missing"

    if engagement_rung is CrossBorderTransfer.PERMITTED_WITH_CONSENT:
        if lawful_basis_present:
            return True, "cross_border_consent"
        return False, "cross_border_consent_missing"

    return True, "cross_border_permitted"


def resolve_permitted_regions(
    engagement_regions: list[str],
    descriptor_regions: list[str],
) -> frozenset[str]:
    if engagement_regions and descriptor_regions:
        allowed = set(engagement_regions) & set(descriptor_regions)
        return frozenset(allowed)
    if engagement_regions:
        return frozenset(engagement_regions)
    if descriptor_regions:
        return frozenset(descriptor_regions)
    return frozenset()


def parse_model_policy(descriptor: dict[str, Any]) -> tuple[ModelSelectionMode, dict[str, Any]]:
    block = descriptor.get("composition") or {}
    policy = block.get("model_policy") if isinstance(block, dict) else None
    if not isinstance(policy, dict):
        return ModelSelectionMode.AUTO, {}
    mode_raw = str(policy.get("selection_mode", "auto")).lower()
    try:
        mode = ModelSelectionMode(mode_raw)
    except ValueError:
        mode = ModelSelectionMode.AUTO
    return mode, policy


def parse_enforcement_level(model_policy: dict[str, Any]) -> EnforcementLevel:
    raw = model_policy.get("enforcement_level")
    if raw is None:
        return EnforcementLevel.ADVISORY
    try:
        return EnforcementLevel(str(raw).lower())
    except ValueError:
        return EnforcementLevel.ADVISORY


def _model_allowed_by_policy(
    provider: str,
    model_id: str,
    model_policy: dict[str, Any],
    selection_mode: ModelSelectionMode,
) -> bool:
    declared = composition_svc.declared_model_keys({"composition": {"model_policy": model_policy}})
    key = model_id.lower()
    full = f"{provider.lower()}/{model_id.lower()}"
    if composition_svc.model_allowed(key, declared) or composition_svc.model_allowed(
        full, declared
    ):
        return True
    if selection_mode is ModelSelectionMode.PINNED:
        pin = model_policy.get("pin") or {}
        if isinstance(pin, dict):
            pin_id = str(pin.get("id", "")).lower()
            pin_provider = str(pin.get("provider", "")).lower()
            return pin_id == key and (not pin_provider or pin_provider == provider.lower())
    if selection_mode is ModelSelectionMode.AUTO:
        allowlist = model_policy.get("allowlist") or []
        if not allowlist:
            return False
    return False


def _is_strict_environment(environment: str | None) -> bool:
    if environment is None:
        return True
    return environment.lower() in _PRODUCTION_ENVIRONMENTS


def evaluate_model_access(
    *,
    provider: str,
    model_id: str,
    environment: str | None,
    selection_mode: ModelSelectionMode,
    model_policy: dict[str, Any],
    permitted_regions: frozenset[str],
    engagement_cross_border: CrossBorderTransfer,
    descriptor_residency: dict[str, Any],
    catalog_region: str | None,
    catalog_jurisdiction: str | None,
    has_catalog_entry: bool,
    catalog_classified: bool,
    data_classes: list[str],
    lawful_basis: dict[str, str],
    dev_permissive: bool,
) -> tuple[DecisionOutcome, str, str, str | None]:
    """Pure access decision — shared by compile-time expansion and request-time evaluate."""

    strict = _is_strict_environment(environment)

    if not has_catalog_entry:
        if strict and not dev_permissive:
            return DecisionOutcome.DENY, "model_unknown", "model.allowlist", None
        return DecisionOutcome.ALLOW, "model_unknown_dev", "model.allowlist", None

    if not catalog_classified:
        if strict and not dev_permissive:
            return DecisionOutcome.DENY, "model_unclassified", "model.catalogue", catalog_region
        return DecisionOutcome.ALLOW, "model_unclassified_dev", "model.catalogue", catalog_region

    if not _model_allowed_by_policy(provider, model_id, model_policy, selection_mode):
        if strict:
            return (
                DecisionOutcome.DENY,
                "model_not_on_allowlist",
                "model.allowlist",
                catalog_region,
            )
        return (
            DecisionOutcome.ALLOW,
            "model_not_on_allowlist_dev",
            "model.allowlist",
            catalog_region,
        )

    region = catalog_region or "global"
    if permitted_regions and region not in permitted_regions and region != "global":
        reroute = policy_svc._pick_reroute_region(region, list(permitted_regions))
        if reroute:
            return DecisionOutcome.REROUTE, "region_not_permitted", "residency.region", reroute
        return DecisionOutcome.DENY, "region_not_permitted", "residency.region", None

    home_jurisdictions = frozenset(
        _jurisdiction_from_region(r) for r in (permitted_regions or frozenset({region}))
    )
    model_j = catalog_jurisdiction or _jurisdiction_from_region(region)
    basis = descriptor_residency.get("basis")
    if isinstance(basis, str):
        basis_val: str | None = basis
    else:
        basis_val = None
    lawful_ok = any(lawful_basis.get(dc) for dc in data_classes) if data_classes else False
    ok, reason = cross_border_permits(
        engagement_cross_border,
        descriptor_basis=basis_val,
        lawful_basis_present=lawful_ok,
        home_jurisdictions=home_jurisdictions,
        model_jurisdiction=model_j,
    )
    if not ok:
        return DecisionOutcome.DENY, reason, "residency.cross_border", None

    return DecisionOutcome.ALLOW, "allowed", "model.routing", region


def build_compiled_digest(
    deployments: tuple[AllowedDeployment, ...], regions: frozenset[str]
) -> str:
    payload = {
        "deployments": [d.model_dump(mode="json") for d in deployments],
        "regions": sorted(regions),
    }
    return catalog_entry_digest(payload)


def build_litellm_config(compiled: CompiledModelPolicy) -> GatewayConfigOut:
    """Emit LiteLLM-oriented config — no Python dependency on LiteLLM itself."""

    model_list = [
        {
            "model_name": f"{d.provider}/{d.model_id}",
            "litellm_params": {
                "model": f"{d.provider}/{d.model_id}",
                "region_name": d.region_name,
            },
        }
        for d in compiled.allowed_deployments
    ]
    config: dict[str, object] = {
        "model_list": model_list,
        "router_settings": {
            "enable_pre_call_checks": True,
            "allowed_regions": sorted(compiled.permitted_regions),
        },
        "general_settings": {
            "enforce_fallback_model_access": True,
        },
        "virtual_key_ref": compiled.virtual_key_ref,
    }
    enforced = config_enforces_fallback_access(config)
    return GatewayConfigOut(
        target=GatewayTargetKind.LITELLM,
        agent_id=compiled.agent_id,
        agent_version_id=compiled.agent_version_id,
        rules_digest=compiled.rules_digest,
        config=config,
        enforcement_level=compiled.enforcement_level,
        fallback_access_enforced=enforced,
    )


def config_enforces_fallback_access(config: dict[str, object]) -> bool:
    """LiteLLM provider fallbacks bypass model access unless this flag is true."""
    general = config.get("general_settings")
    if not isinstance(general, dict):
        return False
    return general.get("enforce_fallback_model_access") is True


def verify_emitted_config(config: dict[str, object]) -> list[str]:
    """Return human-readable findings when emitted config would allow fallback bypass."""
    findings: list[str] = []
    if not config_enforces_fallback_access(config):
        findings.append("general_settings.enforce_fallback_model_access is not true")
    router = config.get("router_settings")
    if not isinstance(router, dict) or router.get("enable_pre_call_checks") is not True:
        findings.append("router_settings.enable_pre_call_checks is not true")
    return findings


def _expand_allowlist_to_deployments(
    org_catalog: list[CatalogEntryOut],
    patterns: tuple[str, ...],
) -> tuple[AllowedDeployment, ...]:
    out: list[AllowedDeployment] = []
    for entry in org_catalog:
        full = f"{entry.provider}/{entry.model_id}"
        for pattern in patterns:
            if fnmatch.fnmatchcase(full.lower(), pattern.lower()) or fnmatch.fnmatchcase(
                entry.model_id.lower(), pattern.lower()
            ):
                out.append(
                    AllowedDeployment(
                        catalog_entry_id=entry.id,
                        provider=entry.provider,
                        model_id=entry.model_id,
                        region_name=entry.primary_region,
                        jurisdiction=entry.jurisdiction,
                    )
                )
                break
    return tuple(out)


async def _load_descriptor_context(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID | None,
) -> tuple[dict[str, Any], UUID, str]:
    agent = await registry_svc.get_agent_detail(session, org_id, agent_id)
    version_id = agent_version_id or agent.current_version_id
    if version_id is None:
        raise AgentContextError("agent has no published version")
    version = await registry_svc.get_agent_version(session, org_id, agent_id, version_id)
    descriptor = await registry_svc.get_version_descriptor(session, org_id, version_id)
    return descriptor, version_id, version.environment


async def compile_agent_model_policy(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID | None = None,
) -> CompiledModelPolicy:
    descriptor, version_id, environment = await _load_descriptor_context(
        session, org_id, agent_id, agent_version_id
    )
    engagement = await repo.get_primary_engagement_for_agent(session, org_id, agent_id)
    selection_mode, model_policy = parse_model_policy(descriptor)
    enforcement = parse_enforcement_level(model_policy)

    data_block = descriptor.get("data") or {}
    residency = data_block.get("residency") if isinstance(data_block, dict) else {}
    if not isinstance(residency, dict):
        residency = {}
    descriptor_regions = list(residency.get("permitted_regions") or [])

    engagement_regions: list[str] = []
    cross_border = CrossBorderTransfer.PROHIBITED
    engagement_id: UUID | None = None
    if engagement is not None:
        engagement_id = engagement.id
        engagement_regions = list(engagement.permitted_regions or [])
        cross_border = CrossBorderTransfer(engagement.cross_border_transfer)

    permitted = resolve_permitted_regions(engagement_regions, descriptor_regions)

    rows = await repo.list_catalog_entries(session, org_id, limit=500)
    catalog = [CatalogEntryOut.model_validate(r) for r in rows]

    patterns: list[str] = []
    if selection_mode is ModelSelectionMode.PINNED:
        pin = model_policy.get("pin") or {}
        if isinstance(pin, dict) and pin.get("id"):
            prov = pin.get("provider") or "*"
            patterns.append(f"{prov}/{pin['id']}".lower())
    else:
        for p in model_policy.get("allowlist") or []:
            if isinstance(p, str):
                patterns.append(p.lower())

    deployments: list[AllowedDeployment] = []
    for entry in catalog:
        if entry.classification_state is ClassificationState.DEPRECATED:
            continue
        outcome, _, _, _ = evaluate_model_access(
            provider=entry.provider,
            model_id=entry.model_id,
            environment=environment,
            selection_mode=selection_mode,
            model_policy=model_policy,
            permitted_regions=permitted,
            engagement_cross_border=cross_border,
            descriptor_residency=residency,
            catalog_region=entry.primary_region,
            catalog_jurisdiction=entry.jurisdiction,
            has_catalog_entry=True,
            catalog_classified=entry.classification_state == ClassificationState.CLASSIFIED,
            data_classes=[],
            lawful_basis={},
            dev_permissive=False,
        )
        if outcome in (DecisionOutcome.ALLOW, DecisionOutcome.REROUTE):
            if patterns:
                full = f"{entry.provider}/{entry.model_id}"
                if not any(
                    fnmatch.fnmatchcase(full.lower(), pat)
                    or fnmatch.fnmatchcase(entry.model_id.lower(), pat)
                    for pat in patterns
                ):
                    continue
            deployments.append(
                AllowedDeployment(
                    catalog_entry_id=entry.id,
                    provider=entry.provider,
                    model_id=entry.model_id,
                    region_name=entry.primary_region,
                    jurisdiction=entry.jurisdiction,
                )
            )

    if not deployments and patterns:
        deployments = list(_expand_allowlist_to_deployments(catalog, tuple(patterns)))

    digest = build_compiled_digest(tuple(deployments), permitted)
    virtual_key = model_policy.get("virtual_key_ref")
    vk = virtual_key if isinstance(virtual_key, str) else None

    return CompiledModelPolicy(
        agent_id=agent_id,
        agent_version_id=version_id,
        engagement_id=engagement_id,
        selection_mode=selection_mode,
        allowed_deployments=tuple(deployments),
        allowed_patterns=tuple(patterns),
        permitted_regions=permitted,
        cross_border_rung=cross_border,
        enforcement_level=enforcement,
        virtual_key_ref=vk,
        compiled_at=datetime.now(UTC),
        rules_digest=digest,
    )


async def evaluate_pre_dispatch(
    session: AsyncSession,
    org_id: UUID,
    request: ModelRoutingEvaluateRequest,
) -> ModelRoutingEvaluateResult:
    compiled = await compile_agent_model_policy(
        session, org_id, request.agent_id, request.agent_version_id
    )
    enforcement = request.enforcement_level or compiled.enforcement_level
    descriptor, version_id, environment = await _load_descriptor_context(
        session, org_id, request.agent_id, request.agent_version_id
    )
    _, model_policy = parse_model_policy(descriptor)
    data_block = descriptor.get("data") or {}
    residency = data_block.get("residency") if isinstance(data_block, dict) else {}
    if not isinstance(residency, dict):
        residency = {}

    settings = get_settings()
    dev_permissive = settings.llm_gateway_dev_permissive and settings.environment == "development"

    entry = await repo.get_catalog_entry_by_provider_model(
        session, org_id, request.model_provider, request.model_id
    )
    if entry is None:
        entry = await repo.resolve_alias(session, org_id, request.model_id)

    catalog_region = entry.primary_region if entry else request.region_hint
    catalog_jurisdiction = entry.jurisdiction if entry else None
    has_entry = entry is not None
    classified = (
        entry is not None and entry.classification_state == ClassificationState.CLASSIFIED.value
    )

    env = request.environment or environment
    outcome, reason, rule_id, effective_region = evaluate_model_access(
        provider=request.model_provider,
        model_id=request.model_id,
        environment=env,
        selection_mode=compiled.selection_mode,
        model_policy=model_policy,
        permitted_regions=compiled.permitted_regions,
        engagement_cross_border=compiled.cross_border_rung,
        descriptor_residency=residency,
        catalog_region=catalog_region,
        catalog_jurisdiction=catalog_jurisdiction,
        has_catalog_entry=has_entry,
        catalog_classified=classified,
        data_classes=request.data_classes,
        lawful_basis=request.lawful_basis,
        dev_permissive=dev_permissive,
    )

    would_block = outcome is DecisionOutcome.DENY and enforcement is EnforcementLevel.BLOCKING
    if outcome is DecisionOutcome.DENY and enforcement is EnforcementLevel.OVERRIDEABLE:
        would_block = False
    if outcome is DecisionOutcome.DENY and enforcement is EnforcementLevel.ADVISORY:
        would_block = False

    http_status = 200
    if would_block:
        http_status = 403
    elif outcome is DecisionOutcome.REROUTE:
        http_status = 200

    policy_decision_id: UUID | None = None
    if outcome is not DecisionOutcome.ALLOW:
        policy_decision_id = await policy_svc.record_model_routing_decision(
            session,
            org_id,
            agent_id=request.agent_id,
            agent_version_id=version_id,
            engagement_id=compiled.engagement_id,
            outcome=outcome,
            reason_code=reason,
            rule_id=rule_id,
            subject_ref=request.subject_ref,
            data_classes=request.data_classes,
            requested_region=catalog_region,
            effective_region=effective_region,
        )

    if outcome is DecisionOutcome.DENY and reason in {"model_unknown", "model_unclassified"}:
        await _ensure_unclassified_catalog_row(
            session, org_id, request.model_provider, request.model_id
        )
        await assurance_svc.record_finding(
            session,
            org_id,
            FindingCreate(
                agent_id=request.agent_id,
                agent_version_id=version_id,
                source=FindingSource.POLICY,
                category=FindingCategory.RESIDENCY_VIOLATION,
                severity=Severity.HIGH,
                title=(
                    f"Unknown model {request.model_provider}/{request.model_id} "
                    "blocked for production"
                ),
                detail="Classify the model in the catalogue or update the agent allowlist.",
                subject_ref=request.subject_ref,
            ),
        )

    return ModelRoutingEvaluateResult(
        outcome=outcome.value,
        would_block=would_block,
        http_status=http_status,
        reason_code=reason,
        rule_id=rule_id,
        effective_region=effective_region,
        catalog_entry_id=entry.id if entry else None,
        policy_decision_id=policy_decision_id,
        compiled_rules_digest=compiled.rules_digest,
    )


async def _ensure_unclassified_catalog_row(
    session: AsyncSession, org_id: UUID, provider: str, model_id: str
) -> None:
    existing = await repo.get_catalog_entry_by_provider_model(session, org_id, provider, model_id)
    if existing is not None:
        return
    payload = {
        "provider": provider,
        "model_id": model_id,
        "hosting_mode": "vendor_api",
        "primary_region": "global",
        "jurisdiction": "UNKNOWN",
        "classification_state": ClassificationState.UNCLASSIFIED.value,
        "source": "observed",
        "data_handling_terms": "unknown",
        "valid_from": date.today(),
        "digest": catalog_entry_digest(
            {"provider": provider, "model_id": model_id, "observed": True}
        ),
    }
    await repo.insert_catalog_entry(session, org_id, payload)


async def list_catalog(
    session: AsyncSession,
    org_id: UUID,
    *,
    classification: str | None = None,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> CatalogPage:
    rows = await repo.list_catalog_entries(
        session, org_id, classification=classification, search=search, limit=limit, offset=offset
    )
    total = await repo.count_catalog_entries(
        session, org_id, classification=classification, search=search
    )
    unclassified = await repo.count_catalog_entries(
        session, org_id, classification=ClassificationState.UNCLASSIFIED.value
    )
    return CatalogPage(
        items=[CatalogEntryOut.model_validate(r) for r in rows],
        total=total,
        unclassified_count=unclassified,
    )


async def create_catalog_entry(
    session: AsyncSession, org_id: UUID, payload: CatalogEntryCreate
) -> CatalogEntryOut:
    valid_from = payload.valid_from or date.today()
    digest_payload = payload.model_dump()
    digest_payload["valid_from"] = valid_from.isoformat()
    values = {
        **payload.model_dump(exclude={"valid_from"}),
        "valid_from": valid_from,
        "digest": catalog_entry_digest(digest_payload),
    }
    row = await repo.insert_catalog_entry(session, org_id, values)
    return CatalogEntryOut.model_validate(row)


async def ingest_gateway_log(
    session: AsyncSession, org_id: UUID, payload: GatewayLogIngest
) -> None:
    await repo.insert_gateway_log(
        session,
        org_id,
        {
            "agent_id": payload.agent_id,
            "agent_version_id": payload.agent_version_id,
            "engagement_id": payload.engagement_id,
            "model_provider": payload.model_provider,
            "model_id": payload.model_id,
            "region_used": payload.region_used,
            "virtual_key_ref": payload.virtual_key_ref,
            "outcome": payload.outcome,
            "log_digest": payload.log_digest,
            "logged_at": payload.logged_at,
        },
    )
    if payload.agent_id is not None:
        await detect_drift_for_observed_model(
            session,
            org_id,
            agent_id=payload.agent_id,
            agent_version_id=payload.agent_version_id,
            provider=payload.model_provider,
            model_id=payload.model_id,
            subject_ref=payload.log_digest,
        )


def _split_model_ref(model: str) -> tuple[str, str]:
    if "/" in model:
        provider, ident = model.split("/", 1)
        return provider.strip(), ident.strip()
    return "unknown", model.strip()


async def scan_run_for_model_drift(session: AsyncSession, org_id: UUID, run_id: UUID) -> int:
    """Observe ``run_steps.model`` — detection only, never blocks live traffic."""
    detail = await operations_svc.build_run_detail(session, org_id, run_id)
    seen = 0
    for step in detail.steps:
        if not step.model or step.kind.value != "llm":
            continue
        provider, model_id = _split_model_ref(step.model)
        await detect_drift_for_observed_model(
            session,
            org_id,
            agent_id=detail.run.agent_id,
            agent_version_id=None,
            provider=provider,
            model_id=model_id,
            subject_ref=f"{run_id}:{step.seq}",
        )
        seen += 1
    return seen


async def detect_drift_for_observed_model(
    session: AsyncSession,
    org_id: UUID,
    *,
    agent_id: UUID,
    agent_version_id: UUID | None,
    provider: str,
    model_id: str,
    subject_ref: str | None,
) -> None:
    """Post-hoc drift — observed model not in compiled allow-set implies bypass or stale config."""

    compiled = await compile_agent_model_policy(session, org_id, agent_id, agent_version_id)
    key = f"{provider.lower()}/{model_id.lower()}"
    allowed = {f"{d.provider.lower()}/{d.model_id.lower()}" for d in compiled.allowed_deployments}
    if key in allowed:
        return
    for pattern in compiled.allowed_patterns:
        if fnmatch.fnmatchcase(key, pattern):
            return

    await assurance_svc.record_finding(
        session,
        org_id,
        FindingCreate(
            agent_id=agent_id,
            agent_version_id=agent_version_id or compiled.agent_version_id,
            source=FindingSource.DRIFT,
            category=FindingCategory.RESIDENCY_VIOLATION,
            severity=Severity.CRITICAL,
            title=f"Model drift: {provider}/{model_id} was not permitted by routing policy",
            detail=(
                "The gateway was bypassed, configuration is stale, or a fallback crossed "
                "a border. Observation does not block traffic — fix gateway routing or "
                "update the catalogue and re-publish."
            ),
            subject_ref=subject_ref,
        ),
    )


async def routing_overview(session: AsyncSession, org_id: UUID) -> RoutingOverview:
    catalog = await list_catalog(
        session,
        org_id,
        classification=ClassificationState.UNCLASSIFIED.value,
        limit=20,
    )
    decisions, _ = await policy_svc.list_policy_decisions(
        session,
        org_id,
        outcomes=[DecisionOutcome.DENY.value, DecisionOutcome.REROUTE.value],
        limit=15,
    )
    recent_denials = [
        {
            "occurred_at": d.occurred_at.isoformat(),
            "outcome": d.outcome.value,
            "reason_code": d.reason_code,
            "agent_id": str(d.agent_id) if d.agent_id else None,
            "rule_id": d.rule_id,
        }
        for d in decisions
    ]
    findings_page = await assurance_svc.list_findings(
        session,
        org_id,
        category=[FindingCategory.RESIDENCY_VIOLATION.value],
        limit=10,
    )
    drift = [
        {
            "title": f.title,
            "severity": f.severity.value,
            "agent_id": str(f.agent_id) if f.agent_id else None,
            "last_seen_at": f.last_seen_at.isoformat(),
        }
        for f in findings_page.items
        if f.source is FindingSource.DRIFT
    ]
    return RoutingOverview(
        unclassified_models=catalog.items,
        recent_denials=recent_denials,
        drift_findings=drift,
    )


async def seed_reference_catalog(session: AsyncSession, org_id: UUID) -> None:
    """Shipped global rows (org_id NULL) — imported offline in airgap via bundle path."""
    samples = [
        CatalogEntryCreate(
            provider="anthropic",
            model_id="claude-sonnet-4-5",
            display_name="Claude Sonnet 4.5",
            primary_region="us-east-1",
            jurisdiction="US",
            data_handling_terms="provider_default",
            source="operator_assertion",
        ),
        CatalogEntryCreate(
            provider="anthropic",
            model_id="claude-sonnet-4",
            display_name="Claude Sonnet 4",
            primary_region="eu-west-1",
            jurisdiction="EU",
            cross_border_ok=False,
            data_handling_terms="zero_retention",
            source="vendor_doc",
        ),
        CatalogEntryCreate(
            provider="openai",
            model_id="gpt-4o",
            display_name="GPT-4o",
            primary_region="us-east-1",
            jurisdiction="US",
            source="operator_assertion",
        ),
        CatalogEntryCreate(
            provider="azure-openai",
            model_id="gpt-4o",
            display_name="Azure OpenAI GPT-4o",
            hosting_mode="cloud_managed",
            primary_region="eu-west-1",
            jurisdiction="EU",
            source="customer_override",
        ),
    ]
    for sample in samples:
        existing = await repo.get_catalog_entry_by_provider_model(
            session,
            org_id,
            sample.provider,
            sample.model_id,
        )
        if existing is not None:
            continue
        valid_from = date.today()
        digest_payload = sample.model_dump()
        digest_payload["valid_from"] = valid_from.isoformat()
        await repo.insert_catalog_entry(
            session,
            None,
            {
                **sample.model_dump(),
                "valid_from": valid_from,
                "digest": catalog_entry_digest(digest_payload),
            },
        )


# Router control-plane (runtime deployments, routes, signed snapshots).
from app.domains.model_routing import runtime_ops as _runtime  # noqa: E402

ProjectNotFoundError = _runtime.ProjectNotFoundError
DeploymentNotFoundError = _runtime.DeploymentNotFoundError
RouteNotFoundError = _runtime.RouteNotFoundError
SnapshotNotFoundError = _runtime.SnapshotNotFoundError
RouterCompileError = _runtime.RouterCompileError
InvalidReferenceError = _runtime.InvalidReferenceError

create_deployment = _runtime.create_deployment
list_project_deployments = _runtime.list_project_deployments
update_deployment = _runtime.update_deployment
disable_deployment = _runtime.disable_deployment
create_route = _runtime.create_route
list_project_routes = _runtime.list_project_routes
update_route = _runtime.update_route
simulate_route = _runtime.simulate_route
compile_project_snapshot = _runtime.compile_project_snapshot
get_snapshot = _runtime.get_snapshot
get_gateway_config_snapshot = _runtime.get_gateway_config_snapshot
signing_public_key_pem = _runtime.signing_public_key_pem
require_project = _runtime.require_project
