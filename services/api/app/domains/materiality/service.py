"""Materiality orchestration: build the context, run the rules, record the decision.

The judgement itself lives in ``rules.py`` and is pure. This module's only job is to
assemble the facts the rules need — the baseline's approved scope, the governing
framework, outstanding critical vulnerabilities, the organisation's own overrides — and
to persist what the engine concluded.

That separation is what makes the engine trustworthy: the same diff can be re-ruled
under a different framework, or re-ruled after the rule set is tuned, without touching
the recorded diff. A reviewer can therefore ask "what would this have been judged under
their rules?" and get an answer.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.evidence import service as evidence_service
from app.domains.evidence.schemas import (
    EvidenceKind,
    EvidenceOutcome,
    EvidenceRecord,
)
from app.domains.materiality import repository as repo
from app.domains.materiality.rules import (
    IMMATERIAL_RULES,
    MATERIAL_RULES,
    REVIEW_RULES,
    MaterialityContext,
    apply_verdicts,
    assess_diff,
    describe_rule,
    rule_catalogue,
)
from app.domains.materiality.schemas import (
    AdjudicationOut,
    AffectedAccreditation,
    AssessmentOut,
    ReviewQueue,
    ReviewQueueItem,
    RuleCatalogue,
    RuleOut,
)
from app.domains.releases.differ import diff_descriptors
from app.domains.releases.schemas import Materiality, ReleaseDiff

log = logging.getLogger(__name__)

#: Marker that turns an adjudication into a standing override. Parsed by
#: fetch_rule_overrides, so the prefix is part of the contract between the two.
OVERRIDE_PREFIX = "rule-override:"


class MaterialityError(Exception):
    """Base for materiality domain failures."""


class ChangeNotFoundError(MaterialityError):
    pass


class ReleaseNotFoundError(MaterialityError):
    pass


class AlreadyAdjudicatedError(MaterialityError):
    """A change already carries a human decision.

    Re-adjudicating would overwrite the record of who decided what, which is the one
    thing the queue exists to preserve.
    """


class UnknownRuleError(MaterialityError):
    pass


# ----------------------------------------------------------------------
# Context assembly
# ----------------------------------------------------------------------


async def build_context(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID | None,
    *,
    framework_slug: str | None = None,
) -> MaterialityContext:
    """Gather everything the rules cannot read off a diff.

    Called before every assessment rather than cached: a critical CVE published an
    hour ago has to change the verdict on a release being evaluated now, and a stale
    context would let it through.
    """
    overrides_raw = await repo.fetch_rule_overrides(session, org_id)
    overrides = {
        rule_id: Materiality(value)
        for rule_id, value in overrides_raw.items()
        if value in {m.value for m in Materiality}
    }

    if agent_id is None:
        return MaterialityContext(framework_slug=framework_slug, overrides=overrides)

    classes, regions = await repo.fetch_baseline_scope(session, org_id, agent_id)
    cves = await repo.fetch_critical_cve_components(session, org_id, agent_id)
    slug = framework_slug or await repo.fetch_framework_for_accreditation(session, org_id, agent_id)

    return MaterialityContext(
        framework_slug=slug,
        approved_data_classes=classes,
        approved_regions=regions,
        critical_cve_components=cves,
        overrides=overrides,
    )


# ----------------------------------------------------------------------
# Assessment
# ----------------------------------------------------------------------


async def assess_descriptors(
    session: AsyncSession,
    org_id: UUID,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    agent_id: UUID | None = None,
    framework_slug: str | None = None,
) -> AssessmentOut:
    """Rule on two descriptors without persisting anything.

    This is what the CI gate calls. It must work for an agent that has never been
    registered, because the entire point of shifting governance left is that a
    developer learns a change is material *before* they merge it.
    """
    context = await build_context(session, org_id, agent_id, framework_slug=framework_slug)
    diff = diff_descriptors(before, after)
    assessment = assess_diff(diff, context)

    affected: list[AffectedAccreditation] = []
    if agent_id is not None and assessment.verdict is not Materiality.IMMATERIAL:
        rows = await repo.fetch_affected_accreditations(session, org_id, agent_id)
        affected = [AffectedAccreditation(**row) for row in rows]

    return AssessmentOut(
        verdict=assessment.verdict,
        accreditation_impact=assessment.accreditation_impact,
        headline=assessment.headline,
        material_count=assessment.material_count,
        review_count=assessment.review_count,
        immaterial_count=assessment.immaterial_count,
        rules_fired=list(assessment.rules_fired),
        changes=list(assessment.changes),
        affected_accreditations=affected,
    )


async def assess_release(
    session: AsyncSession,
    org_id: UUID,
    release_id: UUID,
    *,
    framework_slug: str | None = None,
    persist: bool = True,
) -> AssessmentOut:
    """Rule on a persisted release and write the verdicts back onto its changes.

    Writes an evidence event of kind ``materiality_verdict`` whatever the outcome. An
    immaterial verdict is evidence too — it is the record that the change was examined
    and found not to matter, which is precisely what a reviewer asks for when they want
    to know whether anybody looked.
    """
    found = await repo.get_release_with_agent(session, org_id, release_id)
    if found is None:
        raise ReleaseNotFoundError(f"release {release_id} not found")
    release, agent = found

    before: dict[str, Any] = {}
    if release.from_version_id is not None:
        before = await repo.get_descriptor(session, org_id, release.from_version_id) or {}
    after = await repo.get_descriptor(session, org_id, release.to_version_id) or {}

    context = await build_context(session, org_id, agent.id, framework_slug=framework_slug)

    # Re-rule the *persisted* changes rather than re-diffing, so an adjudication
    # already recorded against a change id is not orphaned by a fresh diff producing
    # new ids.
    stored = await repo.fetch_changes_for_release(session, org_id, release_id)
    if stored:
        diff = ReleaseDiff(
            from_semver=None,
            to_semver="",
            changes=[_to_semantic(c) for c in stored],
        )
    else:
        diff = diff_descriptors(before, after)

    assessment = assess_diff(diff, context)

    if persist and stored:
        # Preserve human decisions: a change somebody has already adjudicated keeps
        # their verdict, not the engine's.
        assignments = [
            (row.id, ruled.verdict.value, list(ruled.rules_fired))
            for row, ruled in zip(stored, assessment.changes, strict=True)
            if row.adjudicated_at is None
        ]
        await repo.bulk_update_verdicts(session, org_id, assignments)

    rows = await repo.fetch_affected_accreditations(session, org_id, agent.id)
    affected = [AffectedAccreditation(**row) for row in rows]

    if persist:
        await evidence_service.record_one(
            session,
            org_id,
            EvidenceRecord(
                kind=EvidenceKind.MATERIALITY_VERDICT,
                occurred_at=datetime.now(UTC),
                agent_id=agent.id,
                agent_version_id=release.to_version_id,
                actor="service:materiality",
                action="assess_release",
                outcome=(
                    EvidenceOutcome.FAIL
                    if assessment.verdict is Materiality.MATERIAL
                    else EvidenceOutcome.PASS
                ),
                subject_ref=release.release_tag,
                decision=assessment.verdict.value,
                reason_code=assessment.accreditation_impact.value,
                detail={
                    "material_count": assessment.material_count,
                    "review_count": assessment.review_count,
                    "immaterial_count": assessment.immaterial_count,
                    "rules_fired": ",".join(assessment.rules_fired)[:512],
                    "framework": context.framework_slug or "none",
                },
                detected_by="computed",
            ),
        )

    return AssessmentOut(
        verdict=assessment.verdict,
        accreditation_impact=assessment.accreditation_impact,
        headline=assessment.headline,
        material_count=assessment.material_count,
        review_count=assessment.review_count,
        immaterial_count=assessment.immaterial_count,
        rules_fired=list(assessment.rules_fired),
        changes=list(assessment.changes),
        affected_accreditations=affected,
    )


def _to_semantic(row: Any) -> Any:
    """Rebuild a ``SemanticChange`` from a persisted row.

    Local import to avoid a module-level cycle with the releases schemas, which import
    nothing from this domain but are imported by it in several places.
    """
    from app.domains.releases.schemas import SemanticChange

    return SemanticChange(
        category=row.category,
        operation=row.operation,
        path=row.path,
        subject=row.subject,
        before_value=row.before_value,
        after_value=row.after_value,
        summary=row.summary,
        detail=row.detail,
        impacts=frozenset(row.impacts or ()),
        severity=row.severity,
        verdict=row.verdict,
        rules_fired=list(row.rules_fired or ()),
        detected_by=row.detected_by,
    )


# ----------------------------------------------------------------------
# Adjudication
# ----------------------------------------------------------------------


async def adjudicate(
    session: AsyncSession,
    org_id: UUID,
    change_id: UUID,
    *,
    verdict: Materiality,
    reason: str,
    actor: str,
    apply_to_rule: bool = False,
) -> AdjudicationOut:
    """Record a human ruling on a change the engine routed for review.

    ``apply_to_rule`` is what makes the product's moat deepen with use: the customer's
    decision becomes a standing override, so the same change never reaches the queue
    twice. The override is stored as part of this adjudication rather than in a table
    of its own, which keeps every override traceable to the decision that created it.
    """
    change = await repo.get_change(session, org_id, change_id)
    if change is None:
        raise ChangeNotFoundError(f"change {change_id} not found")
    if change.adjudicated_at is not None:
        raise AlreadyAdjudicatedError(
            f"change {change_id} was already ruled {change.verdict} by {change.adjudicated_by}"
        )

    previous = Materiality(change.verdict)

    override_rule: str | None = None
    stored_reason = reason
    if apply_to_rule:
        rules = list(change.rules_fired or ())
        if not rules:
            raise UnknownRuleError("this change fired no rule, so there is nothing to override")
        override_rule = rules[0]
        stored_reason = f"{OVERRIDE_PREFIX}{override_rule} {reason}"

    updated = await repo.update_change_verdict(
        session,
        org_id,
        change_id,
        verdict=verdict.value,
        actor=actor,
        reason=stored_reason,
    )
    if updated is None:
        raise ChangeNotFoundError(f"change {change_id} not found")

    await evidence_service.record_one(
        session,
        org_id,
        EvidenceRecord(
            kind=EvidenceKind.MATERIALITY_VERDICT,
            occurred_at=datetime.now(UTC),
            actor=actor,
            action="adjudicate_change",
            outcome=EvidenceOutcome.OBSERVED,
            subject_ref=str(change_id),
            decision=verdict.value,
            reason_code="human_adjudication",
            detail={
                "previous_verdict": previous.value,
                "rules_fired": ",".join(change.rules_fired or ())[:512],
                "rule_override": override_rule or "none",
            },
            detected_by="manual",
        ),
    )

    return AdjudicationOut(
        change_id=change_id,
        verdict=verdict,
        previous_verdict=previous,
        adjudicated_by=actor,
        adjudicated_at=updated.adjudicated_at or datetime.now(UTC),
        reason=reason,
        rule_override_created=override_rule,
    )


# ----------------------------------------------------------------------
# Queue and catalogue
# ----------------------------------------------------------------------


async def get_review_queue(
    session: AsyncSession, org_id: UUID, *, limit: int = 50, offset: int = 0
) -> ReviewQueue:
    rows = await repo.fetch_review_queue(session, org_id, limit=limit, offset=offset)
    total = await repo.count_review_queue(session, org_id)

    return ReviewQueue(
        items=[
            ReviewQueueItem(
                change_id=row["change_id"],
                release_id=row["release_id"],
                agent_id=row["agent_id"],
                agent_urn=row["agent_urn"],
                agent_display_name=row["agent_display_name"],
                category=row["category"],
                subject=row["subject"],
                summary=row["summary"],
                severity=row["severity"],
                rules_fired=list(row["rules_fired"] or ()),
                accreditation_count=row["accreditation_count"],
                customer_names=[n for n in (row["customer_names"] or ()) if n],
                created_at=row["created_at"],
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_rule_catalogue(session: AsyncSession, org_id: UUID) -> RuleCatalogue:
    """The whole rule set plus this organisation's overrides.

    Rendered in the settings screen and embedded in the accreditation pack: a customer
    asked to accept automated suspension reads the rules before agreeing to it.
    """
    overrides_raw = await repo.fetch_rule_overrides(session, org_id)
    overrides = {
        rule_id: Materiality(value)
        for rule_id, value in overrides_raw.items()
        if value in {m.value for m in Materiality}
    }

    return RuleCatalogue(
        rules=[
            RuleOut(
                id=rule.id,
                title=rule.title,
                verdict=overrides.get(rule.id, rule.verdict),
                rationale=rule.rationale,
            )
            for rule in rule_catalogue()
        ],
        material_count=len(MATERIAL_RULES),
        review_count=len(REVIEW_RULES),
        immaterial_count=len(IMMATERIAL_RULES),
        overrides=overrides,
    )


def explain(rule_id: str) -> RuleOut:
    """Resolve a stored rule id to its current text.

    Verdicts persist but rule sets evolve, so a release ruled last quarter must still
    be explainable. ``release_changes.rules_fired`` stores ids precisely so this
    lookup, rather than re-evaluation, answers the question.
    """
    rule = describe_rule(rule_id)
    if rule is None:
        raise UnknownRuleError(f"no rule with id {rule_id!r}")
    return RuleOut(id=rule.id, title=rule.title, verdict=rule.verdict, rationale=rule.rationale)


def rule_verdicts_for(changes: Any, context: MaterialityContext | None = None) -> Any:
    """Re-export for callers that hold changes but no session.

    The releases domain needs to rule on a diff it has just computed and has no reason
    to reach into ``rules`` directly.
    """
    return apply_verdicts(changes, context)
