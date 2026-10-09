"""Policy business logic — publish signed versions and evaluate requests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.evidence import service as evidence_svc
from app.domains.evidence.schemas import DetectedBy, EvidenceKind, EvidenceOutcome, EvidenceRecord
from app.domains.policy import repository as repo
from app.domains.policy.schemas import (
    DecisionOutcome,
    EvaluationRequest,
    EvaluationResult,
    PolicyDecisionOut,
    PolicyDomain,
    PolicyPublish,
    PolicySummary,
    PolicyVersionOut,
    RuleSet,
)
from app.providers.signing import build_signer

DEFAULT_RESIDENCY_POLICY_YAML = """
residency:
  - id: residency.customer_pii
    data_classes: [customer_pii, pii]
    permitted_regions: [eu-west-1, eu-central-1, GB]
    special_category: true
  - id: residency.general
    data_classes: [operational, claims_metadata]
    permitted_regions: [eu-west-1, us-east-1, GB]
tool_allowlist:
  id: tools.default
  allowed_tools: [claims_database, read_claim, search_kb]
oversight:
  id: oversight.financial_write
  action_classes: [financial_write, approve_payment]
""".strip()

_SPECIAL_CATEGORY_PREFIXES = ("special_", "customer_pii", "health_", "biometric")


class PolicyError(Exception):
    """Base for everything this module raises."""


class PolicyNotFoundError(PolicyError):
    def __init__(self, policy_id: UUID) -> None:
        super().__init__(f"policy {policy_id} not found")
        self.policy_id = policy_id


class PolicyVersionError(PolicyError):
    pass


def parse_rules_yaml(rules_yaml: str) -> RuleSet:
    loaded = yaml.safe_load(rules_yaml)
    if not isinstance(loaded, dict):
        raise PolicyVersionError("policy YAML must be a mapping at the top level")
    return RuleSet.model_validate(loaded)


def rules_digest(parsed: RuleSet) -> str:
    """Stable digest so two publishes of the same logical rules share a fingerprint."""
    canonical = json.dumps(parsed.model_dump(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _region_prefix(region: str) -> str:
    if region.upper() in {"GB", "EU"}:
        return region.lower()
    if "-" in region:
        return region.split("-", 1)[0].lower()
    return region.lower()


def _pick_reroute_region(requested: str, permitted: list[str]) -> str | None:
    if not permitted:
        return None
    req_prefix = _region_prefix(requested)
    for candidate in permitted:
        if _region_prefix(candidate) == req_prefix:
            return candidate
    return permitted[0]


def _is_special_category(data_class: str) -> bool:
    lowered = data_class.lower()
    return any(lowered.startswith(p) or lowered == p for p in _SPECIAL_CATEGORY_PREFIXES)


def evaluate_rules(rules: RuleSet, request: EvaluationRequest) -> EvaluationResult:
    """Pure evaluation — every branch is unit-tested without a database."""

    if rules.tool_allowlist and request.tool_name:
        allowed = {t.lower() for t in rules.tool_allowlist.allowed_tools}
        if request.tool_name.lower() not in allowed:
            return EvaluationResult(
                outcome=DecisionOutcome.DENY,
                reason_code="tool_not_allowlisted",
                rule_id=rules.tool_allowlist.id,
            )

    if rules.oversight and request.action_class:
        required = {a.lower() for a in rules.oversight.action_classes}
        if request.action_class.lower() in required:
            return EvaluationResult(
                outcome=DecisionOutcome.REQUIRE_APPROVAL,
                reason_code="human_approval_required",
                rule_id=rules.oversight.id,
            )

    for data_class in request.data_classes:
        if _is_special_category(data_class) and not request.lawful_basis.get(data_class):
            return EvaluationResult(
                outcome=DecisionOutcome.DENY,
                reason_code="special_category_no_lawful_basis",
                rule_id="residency.lawful_basis",
            )

    if request.requested_region:
        for rule in rules.residency:
            classes = {c.lower() for c in rule.data_classes}
            touched = [dc for dc in request.data_classes if dc.lower() in classes]
            if not touched:
                continue
            permitted = rule.permitted_regions
            if request.requested_region in permitted:
                continue
            reroute = _pick_reroute_region(request.requested_region, permitted)
            if reroute:
                return EvaluationResult(
                    outcome=DecisionOutcome.REROUTE,
                    reason_code="region_not_permitted",
                    rule_id=rule.id,
                    effective_region=reroute,
                )
            return EvaluationResult(
                outcome=DecisionOutcome.DENY,
                reason_code="region_not_permitted",
                rule_id=rule.id,
            )

    return EvaluationResult(
        outcome=DecisionOutcome.ALLOW,
        reason_code="allowed",
        rule_id="policy.default_allow",
    )


async def publish_version(
    session: AsyncSession,
    org_id: UUID,
    policy_id: UUID,
    payload: PolicyPublish,
) -> PolicyVersionOut:
    policy = await repo.get_policy(session, org_id, policy_id)
    if policy is None:
        raise PolicyNotFoundError(policy_id)

    parsed = parse_rules_yaml(payload.rules_yaml)
    digest = rules_digest(parsed)
    now = datetime.now(UTC)

    await repo.close_current_version(session, org_id, policy_id, effective_to=now)

    signer = build_signer()
    signature = signer.sign(payload.rules_yaml.encode("utf-8"))

    version = await repo.insert_policy_version(
        session,
        org_id,
        {
            "policy_id": policy_id,
            "semver": payload.semver,
            "rules_yaml": payload.rules_yaml,
            "rules_json": parsed.model_dump(),
            "rules_digest": digest,
            "effective_from": now,
            "signature": signature,
            "signing_key_ref": signer.key_id,
            "published_by": payload.published_by,
        },
    )
    return PolicyVersionOut.model_validate(version)


async def evaluate(
    session: AsyncSession, org_id: UUID, policy_id: UUID, request: EvaluationRequest
) -> EvaluationResult:
    policy = await repo.get_policy(session, org_id, policy_id)
    if policy is None:
        raise PolicyNotFoundError(policy_id)
    if not policy.is_enabled:
        return EvaluationResult(
            outcome=DecisionOutcome.ALLOW,
            reason_code="policy_disabled",
            rule_id="policy.disabled",
        )

    current = await repo.get_current_version(session, org_id, policy_id)
    if current is None:
        parsed = parse_rules_yaml(DEFAULT_RESIDENCY_POLICY_YAML)
    else:
        parsed = RuleSet.model_validate(current.rules_json)

    result = evaluate_rules(parsed, request)

    if result.outcome is not DecisionOutcome.ALLOW:
        occurred = datetime.now(UTC)
        evidence_id = await evidence_svc.record_one(
            session,
            org_id,
            EvidenceRecord(
                kind=EvidenceKind.POLICY_DECISION,
                occurred_at=occurred,
                agent_id=request.agent_id,
                agent_version_id=request.agent_version_id,
                engagement_id=request.engagement_id,
                actor="service:policy",
                action="evaluate",
                outcome=_evidence_outcome(result.outcome),
                subject_ref=request.subject_ref,
                region=result.effective_region or request.requested_region,
                data_classes=request.data_classes,
                decision=result.outcome.value,
                reason_code=result.reason_code,
                detail={"rule_id": result.rule_id, "policy_id": str(policy_id)},
                detected_by=DetectedBy.COMPUTED,
            ),
        )
        if current is not None:
            await repo.insert_decision(
                session,
                org_id,
                {
                    "policy_version_id": current.id,
                    "agent_id": request.agent_id,
                    "agent_version_id": request.agent_version_id,
                    "engagement_id": request.engagement_id,
                    "outcome": result.outcome.value,
                    "reason_code": result.reason_code,
                    "rule_id": result.rule_id,
                    "subject_ref": request.subject_ref,
                    "data_classes": request.data_classes,
                    "requested_region": request.requested_region,
                    "effective_region": result.effective_region,
                    "evidence_event_id": evidence_id,
                },
            )

    return result


def _evidence_outcome(outcome: DecisionOutcome) -> EvidenceOutcome:
    mapping = {
        DecisionOutcome.DENY: EvidenceOutcome.DENY,
        DecisionOutcome.REDACT: EvidenceOutcome.REDACT,
        DecisionOutcome.REROUTE: EvidenceOutcome.REROUTE,
        DecisionOutcome.REQUIRE_APPROVAL: EvidenceOutcome.REQUIRE_APPROVAL,
    }
    return mapping.get(outcome, EvidenceOutcome.OBSERVED)


async def create_policy(
    session: AsyncSession,
    org_id: UUID,
    *,
    slug: str,
    name: str,
    domain: PolicyDomain,
    description: str | None = None,
) -> PolicySummary:
    row = await repo.insert_policy(
        session,
        org_id,
        {
            "slug": slug,
            "name": name,
            "description": description,
            "domain": domain.value,
        },
    )
    return PolicySummary.model_validate(row)


async def list_policies(session: AsyncSession, org_id: UUID) -> list[PolicySummary]:
    rows = await repo.list_policies(session, org_id)
    return [PolicySummary.model_validate(r) for r in rows]


async def get_policy_versions(
    session: AsyncSession, org_id: UUID, policy_id: UUID
) -> list[PolicyVersionOut]:
    if await repo.get_policy(session, org_id, policy_id) is None:
        raise PolicyNotFoundError(policy_id)
    rows = await repo.list_versions(session, org_id, policy_id)
    return [PolicyVersionOut.model_validate(r) for r in rows]


async def list_policy_decisions(
    session: AsyncSession,
    org_id: UUID,
    *,
    outcomes: list[str] | None = None,
    agent_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[PolicyDecisionOut], int]:
    rows = await repo.list_decisions(
        session, org_id, outcomes=outcomes, agent_id=agent_id, limit=limit, offset=offset
    )
    total = await repo.count_decisions(session, org_id, outcomes=outcomes, agent_id=agent_id)
    return [PolicyDecisionOut.model_validate(r) for r in rows], total


async def record_model_routing_decision(
    session: AsyncSession,
    org_id: UUID,
    *,
    agent_id: UUID,
    agent_version_id: UUID,
    engagement_id: UUID | None,
    outcome: DecisionOutcome,
    reason_code: str,
    rule_id: str,
    subject_ref: str | None,
    data_classes: list[str],
    requested_region: str | None,
    effective_region: str | None,
) -> UUID:
    """Immutable audit row for gateway pre-dispatch — separate from YAML residency evaluate."""
    policy = await ensure_default_model_use_policy(session, org_id)
    current = await repo.get_current_version(session, org_id, policy.id)
    if current is None:
        raise PolicyVersionError("model-use policy has no published version")

    occurred = datetime.now(UTC)
    evidence_id = await evidence_svc.record_one(
        session,
        org_id,
        EvidenceRecord(
            kind=EvidenceKind.POLICY_DECISION,
            occurred_at=occurred,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            engagement_id=engagement_id,
            actor="service:model_routing",
            action="pre_dispatch",
            outcome=_evidence_outcome(outcome),
            subject_ref=subject_ref,
            region=effective_region or requested_region,
            data_classes=data_classes,
            decision=outcome.value,
            reason_code=reason_code,
            detail={"rule_id": rule_id, "policy_id": str(policy.id)},
            detected_by=DetectedBy.COMPUTED,
        ),
    )
    row = await repo.insert_decision(
        session,
        org_id,
        {
            "policy_version_id": current.id,
            "agent_id": agent_id,
            "agent_version_id": agent_version_id,
            "engagement_id": engagement_id,
            "outcome": outcome.value,
            "reason_code": reason_code,
            "rule_id": rule_id,
            "subject_ref": subject_ref,
            "data_classes": data_classes,
            "requested_region": requested_region,
            "effective_region": effective_region,
            "evidence_event_id": evidence_id,
        },
    )
    return row.id


async def ensure_default_model_use_policy(session: AsyncSession, org_id: UUID) -> PolicySummary:
    existing = await repo.get_policy_by_slug(session, org_id, "model-routing")
    if existing:
        return PolicySummary.model_validate(existing)

    policy = await repo.insert_policy(
        session,
        org_id,
        {
            "slug": "model-routing",
            "name": "Model routing and residency",
            "description": "Pre-dispatch model allow-set compiled from engagements and descriptors",
            "domain": PolicyDomain.MODEL_USE.value,
        },
    )
    rules_yaml = "residency: []\n"
    parsed = parse_rules_yaml(rules_yaml)
    digest = rules_digest(parsed)
    signer = build_signer()
    await repo.insert_policy_version(
        session,
        org_id,
        {
            "policy_id": policy.id,
            "semver": "1.0.0",
            "rules_yaml": rules_yaml,
            "rules_json": parsed.model_dump(),
            "rules_digest": digest,
            "signature": signer.sign(rules_yaml.encode("utf-8")),
            "signing_key_ref": signer.key_id,
            "published_by": "system:seed",
        },
    )
    return PolicySummary.model_validate(policy)


async def ensure_default_residency_policy(session: AsyncSession, org_id: UUID) -> PolicySummary:
    existing = await repo.get_policy_by_slug(session, org_id, "default-residency")
    if existing:
        return PolicySummary.model_validate(existing)

    policy = await repo.insert_policy(
        session,
        org_id,
        {
            "slug": "default-residency",
            "name": "Default residency envelope",
            "description": "Shipped baseline until a tenant publishes their own rules",
            "domain": PolicyDomain.RESIDENCY.value,
        },
    )
    parsed = parse_rules_yaml(DEFAULT_RESIDENCY_POLICY_YAML)
    digest = rules_digest(parsed)
    signer = build_signer()
    await repo.insert_policy_version(
        session,
        org_id,
        {
            "policy_id": policy.id,
            "semver": "1.0.0",
            "rules_yaml": DEFAULT_RESIDENCY_POLICY_YAML,
            "rules_json": parsed.model_dump(),
            "rules_digest": digest,
            "signature": signer.sign(DEFAULT_RESIDENCY_POLICY_YAML.encode("utf-8")),
            "signing_key_ref": signer.key_id,
            "published_by": "system:seed",
        },
    )
    return PolicySummary.model_validate(policy)
