"""Release business logic — persist semantic diffs and govern rollout."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.materiality.rules import MaterialityContext
from app.domains.materiality.rules import apply_verdicts as rule_changes
from app.domains.registry import service as registry_svc
from app.domains.registry.service import VersionNotFoundError, canonical_descriptor_digest
from app.domains.releases import repository as repo
from app.domains.releases.differ import diff_descriptors
from app.domains.releases.interpreter import build_review_brief
from app.domains.releases.schemas import (
    AccreditationImpact,
    ChangeAdjudicateRequest,
    ChangeCategory,
    ChangeOperation,
    EnforcementLevel,
    ImpactDimension,
    Materiality,
    ReleaseCreate,
    ReleaseDetail,
    ReleaseDiff,
    ReleaseGateVerdict,
    ReleasePreviewRequest,
    ReleaseReviewBrief,
    ReleaseState,
    ReleaseSummary,
    ReleaseTransitionRequest,
    SemanticChange,
    Severity,
)

logger = logging.getLogger(__name__)

# Categories where a high-severity change is treated as material by the severity-only
# fallback. Only consulted when the rules engine itself fails; see provisional_verdict.
_CRITICAL_MATERIAL_CATEGORIES = frozenset(
    {
        ChangeCategory.MODEL,
        ChangeCategory.DATA_CLASS,
        ChangeCategory.RESIDENCY,
        ChangeCategory.DELEGATION,
    }
)

_ALLOWED_TRANSITIONS: dict[ReleaseState, frozenset[ReleaseState]] = {
    ReleaseState.DRAFT: frozenset({ReleaseState.PROPOSED, ReleaseState.ABANDONED}),
    ReleaseState.PROPOSED: frozenset(
        {ReleaseState.APPROVED, ReleaseState.DRAFT, ReleaseState.ABANDONED}
    ),
    ReleaseState.APPROVED: frozenset({ReleaseState.ROLLED_OUT, ReleaseState.ABANDONED}),
    ReleaseState.ROLLED_OUT: frozenset({ReleaseState.ROLLED_BACK}),
    ReleaseState.ROLLED_BACK: frozenset(),
    ReleaseState.ABANDONED: frozenset(),
}


class ReleaseError(Exception):
    """Base for everything this module raises."""


class ReleaseNotFoundError(ReleaseError):
    def __init__(self, release_id: UUID) -> None:
        super().__init__(f"release {release_id} not found")
        self.release_id = release_id


class ChangeNotFoundError(ReleaseError):
    def __init__(self, change_id: UUID) -> None:
        super().__init__(f"change {change_id} not found")
        self.change_id = change_id


class InvalidTransitionError(ReleaseError):
    def __init__(self, current: ReleaseState, target: ReleaseState) -> None:
        super().__init__(f"cannot transition from {current.value} to {target.value}")
        self.current = current
        self.target = target


class ReleaseValidationError(ReleaseError):
    pass


class DigestMismatchError(ReleaseError):
    """Approval attempted against a descriptor digest the reviewer did not bind to."""

    def __init__(self) -> None:
        super().__init__(
            "reviewed_descriptor_digest does not match the target version — "
            "fetch a fresh review brief before approving"
        )


def provisional_verdict(change: SemanticChange) -> Materiality:
    """Severity-only fallback, used when the rules engine cannot rule at all.

    Retained for one narrow purpose: if ``materiality`` raises, a release must still get
    a verdict rather than no verdict, and erring towards review beats erring towards
    approval. It is not the product's judgement — ``materiality.rules`` is. Do not reach
    for this because it is simpler; a verdict from here carries no rule id and therefore
    cannot be explained to a reviewer or adjudicated by one.
    """
    if change.severity is Severity.CRITICAL:
        return Materiality.MATERIAL
    if change.severity is Severity.HIGH and change.category in _CRITICAL_MATERIAL_CATEGORIES:
        return Materiality.MATERIAL
    if change.severity in (Severity.HIGH, Severity.MEDIUM):
        return Materiality.NEEDS_REVIEW
    return Materiality.IMMATERIAL


def apply_verdicts(
    changes: list[SemanticChange], context: MaterialityContext | None = None
) -> list[SemanticChange]:
    """Rule every change through the materiality engine.

    One function so the CI gate and the persisted release cannot diverge. They used to:
    the gate ran a severity heuristic while the console ran the rule set, which meant an
    engineer could be told a change was allowed and then find the approval suspended in
    the console an hour later. Nothing erodes confidence in an assurance tool faster than
    two of its own surfaces disagreeing.
    """
    try:
        return rule_changes(changes, context)
    except Exception:
        # The engine is pure, so this should not happen — but the gate sits in a
        # customer's deploy pipeline, and taking their build down is a worse failure
        # than falling back to a coarser verdict that still errs towards review.
        logger.exception("materiality engine failed; falling back to severity verdicts")
        return [c.model_copy(update={"verdict": provisional_verdict(c)}) for c in changes]


def build_gate_verdict(diff: ReleaseDiff) -> ReleaseGateVerdict:
    """Pure CI gate logic — no I/O."""
    material = [c for c in diff.changes if c.verdict is Materiality.MATERIAL]
    review = [c for c in diff.changes if c.verdict is Materiality.NEEDS_REVIEW]
    impact = diff.accreditation_impact

    advisory: list[str] = []
    if review and not material:
        advisory.append(f"{len(review)} change(s) need human review before accreditation can stand")

    # Name the rules that blocked the release. An exit code tells an engineer they are
    # blocked; a rule id tells them what to do about it, and is the thing they quote when
    # they disagree.
    for change in material:
        for rule_id in change.rules_fired:
            entry = f"{rule_id}: {change.summary}"
            if entry not in advisory:
                advisory.append(entry)

    enforcement = (
        EnforcementLevel.HARD
        if material
        else EnforcementLevel.SOFT
        if review
        else EnforcementLevel.ADVISORY
    )

    return ReleaseGateVerdict(
        allowed=len(material) == 0,
        headline=diff.headline(),
        material_count=len(material),
        review_count=len(review),
        accreditation_impact=impact,
        enforcement=enforcement,
        blocking_changes=material,
        advisory=advisory,
    )


def can_transition(current: ReleaseState, target: ReleaseState) -> bool:
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


def _change_to_row(change: SemanticChange) -> dict[str, Any]:
    return {
        "category": change.category.value,
        "operation": change.operation.value,
        "path": change.path,
        "subject": change.subject,
        "before_value": change.before_value,
        "after_value": change.after_value,
        "summary": change.summary,
        "detail": change.detail,
        "impacts": [i.value for i in change.impacts],
        "severity": change.severity.value,
        "verdict": change.verdict.value,
        "rules_fired": list(change.rules_fired),
        "detected_by": change.detected_by,
    }


def _row_to_semantic(row: Any) -> SemanticChange:
    return SemanticChange(
        category=ChangeCategory(row.category),
        operation=ChangeOperation(row.operation),
        path=row.path,
        subject=row.subject,
        before_value=row.before_value,
        after_value=row.after_value,
        summary=row.summary,
        detail=row.detail,
        impacts=frozenset(ImpactDimension(i) for i in (row.impacts or [])),
        severity=Severity(row.severity),
        verdict=Materiality(row.verdict),
        rules_fired=tuple(row.rules_fired or ()),
        detected_by=row.detected_by,
    )


def _summary_from_row(
    release: Any, agent_urn: str, from_semver: str | None, to_semver: str | None
) -> ReleaseSummary:
    to_label = to_semver or "unknown"
    return ReleaseSummary(
        id=release.id,
        agent_id=release.agent_id,
        agent_urn=agent_urn,
        release_tag=release.release_tag,
        title=release.title,
        state=ReleaseState(release.state),
        from_semver=from_semver,
        to_semver=to_label,
        change_count=release.change_count,
        material_count=release.material_count,
        review_count=release.review_count,
        impacts=[ImpactDimension(i) for i in (release.impacts or [])],
        categories=[ChangeCategory(c) for c in (release.categories or [])],
        accreditation_impact=AccreditationImpact(release.accreditation_impact),
        affected_accreditations=release.affected_accreditations,
        vcs_provider=release.vcs_provider,
        vcs_repo=release.vcs_repo,
        vcs_ref=release.vcs_ref,
        vcs_pr_ref=release.vcs_pr_ref,
        proposed_by=release.proposed_by,
        created_at=release.created_at,
    )


async def create_release(
    session: AsyncSession, org_id: UUID, payload: ReleaseCreate
) -> ReleaseDetail:
    if payload.from_version_id == payload.to_version_id:
        raise ReleaseValidationError("from_version_id and to_version_id must differ")

    try:
        before_desc = (
            await registry_svc.get_version_descriptor(session, org_id, payload.from_version_id)
            if payload.from_version_id
            else None
        )
        after_desc = await registry_svc.get_version_descriptor(
            session, org_id, payload.to_version_id
        )
    except VersionNotFoundError as exc:
        raise ReleaseValidationError(str(exc)) from exc

    diff = diff_descriptors(before_desc, after_desc)
    diff = diff.model_copy(update={"changes": apply_verdicts(diff.changes)})

    release = await repo.insert_release(
        session,
        org_id,
        {
            "agent_id": payload.agent_id,
            "from_version_id": payload.from_version_id,
            "to_version_id": payload.to_version_id,
            "release_tag": payload.release_tag,
            "title": payload.title,
            "notes": payload.notes,
            "state": ReleaseState.DRAFT.value,
            "vcs_provider": payload.vcs_provider,
            "vcs_repo": payload.vcs_repo,
            "vcs_ref": payload.vcs_ref,
            "vcs_pr_ref": payload.vcs_pr_ref,
            "proposed_by": payload.proposed_by,
        },
    )

    await repo.insert_release_changes(
        session,
        org_id,
        release.id,
        [_change_to_row(c) for c in diff.changes],
    )

    refreshed = await repo.get_release(session, org_id, release.id)
    assert refreshed is not None
    return await get_release_detail(session, org_id, refreshed.id)


def preview_review_brief(
    before_descriptor: dict[str, Any] | None,
    after_descriptor: dict[str, Any],
    context: MaterialityContext | None = None,
) -> ReleaseReviewBrief:
    diff = diff_descriptors(before_descriptor, after_descriptor)
    diff = diff.model_copy(update={"changes": apply_verdicts(diff.changes, context)})
    digest = canonical_descriptor_digest(after_descriptor)
    return build_review_brief(diff, descriptor_digest=digest)


def preview_release(
    before_descriptor: dict[str, Any] | None,
    after_descriptor: dict[str, Any],
    context: MaterialityContext | None = None,
    *,
    include_brief: bool = True,
) -> ReleaseGateVerdict:
    """Rule on a change without persisting anything. The CI gate.

    Pure, and deliberately so: it takes two descriptors and returns a verdict, with no
    database and no organisation. That is what lets it answer before an agent version
    has been published — which is the only point in a pipeline where the answer is still
    cheap to act on.

    ``context`` carries the approved scope when the caller knows it. Without it the
    engine's pessimistic defaults apply, so an unscoped preview can report review items
    a scoped one would clear.
    """
    diff = diff_descriptors(before_descriptor, after_descriptor)
    diff = diff.model_copy(update={"changes": apply_verdicts(diff.changes, context)})
    verdict = build_gate_verdict(diff)
    if not include_brief:
        return verdict
    digest = canonical_descriptor_digest(after_descriptor)
    brief = build_review_brief(diff, descriptor_digest=digest)
    return verdict.model_copy(update={"review_brief": brief})


async def preview_release_request(payload: ReleasePreviewRequest) -> ReleaseGateVerdict:
    return preview_release(payload.before_descriptor, payload.after_descriptor)


async def get_release_detail(
    session: AsyncSession, org_id: UUID, release_id: UUID
) -> ReleaseDetail:
    row = await repo.fetch_release_row(session, org_id, release_id)
    if row is None:
        raise ReleaseNotFoundError(release_id)

    release, agent_urn, from_semver, to_semver = row
    summary = _summary_from_row(release, agent_urn, from_semver, to_semver)
    changes = await repo.fetch_changes(session, org_id, release_id)
    semantic = [_row_to_semantic(c) for c in changes]
    to_digest = await repo.fetch_version_digest(session, org_id, release.to_version_id)
    diff = ReleaseDiff(
        from_semver=from_semver,
        to_semver=to_semver or "unknown",
        changes=semantic,
    )
    brief = (
        build_review_brief(
            diff,
            descriptor_digest=to_digest or "sha256:unknown",
            release_id=release_id,
        )
        if to_digest
        else None
    )
    return ReleaseDetail(
        **summary.model_dump(),
        notes=release.notes,
        changes=semantic,
        approved_by=release.approved_by,
        approved_at=release.approved_at,
        rolled_out_at=release.rolled_out_at,
        to_descriptor_digest=to_digest,
        reviewed_descriptor_digest=release.reviewed_descriptor_digest,
        review_brief=brief,
    )


async def get_review_brief(
    session: AsyncSession, org_id: UUID, release_id: UUID
) -> ReleaseReviewBrief:
    detail = await get_release_detail(session, org_id, release_id)
    if detail.review_brief is None:
        raise ReleaseNotFoundError(release_id)
    return detail.review_brief


async def list_releases(
    session: AsyncSession,
    org_id: UUID,
    *,
    states: list[str] | None = None,
    agent_id: UUID | None = None,
    material_only: bool = False,
    categories: list[str] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ReleaseSummary], int]:
    rows = await repo.list_releases(
        session,
        org_id,
        states=states,
        agent_id=agent_id,
        material_only=material_only,
        categories=categories,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    total = await repo.count_releases(
        session,
        org_id,
        states=states,
        agent_id=agent_id,
        material_only=material_only,
        categories=categories,
        created_from=created_from,
        created_to=created_to,
    )
    summaries = [
        _summary_from_row(row[0], row.agent_urn, row.from_semver, row.to_semver) for row in rows
    ]
    return summaries, total


async def transition_release(
    session: AsyncSession,
    org_id: UUID,
    release_id: UUID,
    payload: ReleaseTransitionRequest,
) -> ReleaseDetail:
    release = await repo.get_release(session, org_id, release_id)
    if release is None:
        raise ReleaseNotFoundError(release_id)

    current = ReleaseState(release.state)
    target = payload.target_state
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)

    now = datetime.now(UTC)
    values: dict[str, Any] = {"state": target.value}
    if target is ReleaseState.PROPOSED:
        values["proposed_by"] = payload.actor
        values["proposed_at"] = now
    elif target is ReleaseState.APPROVED:
        live_digest = await repo.fetch_version_digest(session, org_id, release.to_version_id)
        if live_digest is None:
            raise ReleaseValidationError("target version not found for this release")
        if not payload.reviewed_descriptor_digest:
            raise ReleaseValidationError(
                "reviewed_descriptor_digest is required when approving a release"
            )
        if payload.reviewed_descriptor_digest != live_digest:
            raise DigestMismatchError()
        values["approved_by"] = payload.actor
        values["approved_at"] = now
        values["reviewed_descriptor_digest"] = live_digest
    elif target is ReleaseState.ROLLED_OUT:
        values["rolled_out_at"] = now
    elif target is ReleaseState.ROLLED_BACK:
        values["rolled_back_at"] = now

    await repo.update_release_state(session, org_id, release_id, values)
    return await get_release_detail(session, org_id, release_id)


async def adjudicate_change(
    session: AsyncSession,
    org_id: UUID,
    release_id: UUID,
    change_id: UUID,
    payload: ChangeAdjudicateRequest,
) -> SemanticChange:
    if await repo.get_release(session, org_id, release_id) is None:
        raise ReleaseNotFoundError(release_id)

    row = await repo.update_change_adjudication(
        session,
        org_id,
        release_id,
        change_id,
        {
            "verdict": payload.verdict.value,
            "adjudicated_by": payload.adjudicated_by,
            "adjudicated_at": datetime.now(UTC),
            "adjudication_reason": payload.adjudication_reason,
        },
    )
    if row is None:
        raise ChangeNotFoundError(change_id)
    return _row_to_semantic(row)
