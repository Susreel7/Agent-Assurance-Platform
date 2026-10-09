"""Accreditation lifecycle, control assembly and pack rendering.

The state machine is the product: every transition is recorded so a reviewer can ask
why something is suspended without inferring from a single column.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.accreditation import repository as repo
from app.domains.accreditation.schemas import (
    AccreditationControlOut,
    AccreditationCreate,
    AccreditationDetail,
    AccreditationPackOut,
    AccreditationState,
    AccreditationSummary,
    ControlAnswerState,
    PackRenderRequest,
    ReadinessGap,
    ReadinessOut,
    TransitionOut,
    TransitionRequest,
)
from app.domains.evidence import service as evidence_service
from app.domains.evidence.schemas import DetectedBy, EvidenceKind, EvidenceOutcome, EvidenceRecord
from app.domains.materiality.rules import DiffAssessment
from app.domains.releases.schemas import AccreditationImpact
from app.providers.objectstore import build_object_store
from app.providers.signing import build_signer

_APPROVAL_VALIDITY_DAYS = 365
_DEFAULT_ATTESTATION_CADENCE_DAYS = 90

# HLD page 5 transitions. Withdrawn is reachable from any non-terminal state.
_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted", "withdrawn"},
    "submitted": {"approved", "draft", "withdrawn"},
    "approved": {"suspended", "expired", "withdrawn"},
    "suspended": {"approved", "expired", "withdrawn"},
    "expired": {"withdrawn"},
    "withdrawn": set(),
}


class AccreditationError(Exception):
    """Base for everything this module raises."""


class AccreditationNotFoundError(AccreditationError):
    def __init__(self, accreditation_id: UUID) -> None:
        super().__init__(f"accreditation {accreditation_id} not found")
        self.accreditation_id = accreditation_id


class InvalidTransitionError(AccreditationError):
    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(f"transition from {from_state!r} to {to_state!r} is not allowed")
        self.from_state = from_state
        self.to_state = to_state


class SelfApprovalError(AccreditationError):
    pass


class PackRenderError(AccreditationError):
    pass


def approver_separation_ok(submitter: str | None, approver: str) -> bool:
    """Separation of duties: the approver must not be the same principal as the submitter."""
    return not submitter or submitter != approver


def release_reaction_kind(impact: AccreditationImpact) -> str:
    """Named action materiality drives — unit-tested without a database."""
    if impact is AccreditationImpact.SUSPENDS:
        return "suspend_accreditations"
    if impact is AccreditationImpact.REQUIRES_REVALIDATION:
        return "schedule_attestation"
    return "advance_baseline"


def transition_allowed(from_state: str | None, to_state: str) -> bool:
    if to_state == "withdrawn":
        return from_state != "withdrawn" and from_state is not None
    if from_state is None:
        return False
    return to_state in _TRANSITIONS.get(from_state, set())


class MappingRow(Protocol):
    """Shape of one ``control_mappings`` row.

    Declared structurally so the classification below can be exercised with plain
    objects: these are the rules that decide whether a control is answerable, and a
    mistake in them misreports a pack to a reviewer.
    """

    evidence_kind: str
    strength: str


def classify_control_answer(
    answer_mode: str,
    mappings: Sequence[MappingRow],
    evidence_counts: dict[str, int],
) -> tuple[ControlAnswerState, str | None, list[str], int]:
    """Pure control assembly logic — testable without a database."""
    kinds = [m.evidence_kind for m in mappings]
    total_events = sum(evidence_counts.get(k, 0) for k in kinds if k)

    if answer_mode == "narrative":
        return ControlAnswerState.NARRATIVE, None, kinds, total_events

    if not mappings:
        return (
            ControlAnswerState.UNANSWERABLE,
            "No evidence mapping exists for this control in the catalogue",
            [],
            0,
        )

    if total_events == 0:
        return (
            ControlAnswerState.UNANSWERABLE,
            f"No evidence events of kinds {', '.join(kinds)} have been recorded for this agent",
            kinds,
            0,
        )

    satisfies = sum(
        1
        for m in mappings
        if m.strength == "satisfies" and evidence_counts.get(m.evidence_kind, 0) > 0
    )
    if satisfies >= 1 and total_events >= len(mappings):
        return ControlAnswerState.ANSWERED, None, kinds, total_events
    if total_events > 0:
        return ControlAnswerState.PARTIAL, None, kinds, total_events
    return (
        ControlAnswerState.UNANSWERABLE,
        "Mapped evidence kinds exist but none satisfy the control outright",
        kinds,
        total_events,
    )


async def create_accreditation(
    session: AsyncSession,
    org_id: UUID,
    payload: AccreditationCreate,
) -> AccreditationDetail:
    version = await repo.get_agent_version(session, org_id, payload.agent_version_id)
    if version is None:
        raise AccreditationError(f"agent version {payload.agent_version_id} not found")
    customer_id: UUID | None = None
    if payload.engagement_id is not None:
        customer_id = await repo.get_engagement_customer(session, org_id, payload.engagement_id)
        if customer_id is None:
            raise AccreditationError("engagement not found for this organisation")

    reference = payload.reference or f"ACC-{uuid4().hex[:8].upper()}"
    now = datetime.now(tz=UTC)
    row = await repo.insert_accreditation(
        session,
        org_id,
        {
            "id": uuid4(),
            "agent_id": version.agent_id,
            "agent_version_id": payload.agent_version_id,
            "framework_id": payload.framework_id,
            "engagement_id": payload.engagement_id,
            "customer_id": customer_id,
            "reference": reference,
            "state": AccreditationState.DRAFT.value,
            "created_at": now,
            "updated_at": now,
        },
    )
    return AccreditationDetail.model_validate(row)


async def get_accreditation_detail(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> AccreditationDetail:
    row = await repo.get_accreditation(session, org_id, accreditation_id)
    if row is None:
        raise AccreditationNotFoundError(accreditation_id)
    return AccreditationDetail.model_validate(row)


async def list_accreditation_summaries(
    session: AsyncSession,
    org_id: UUID,
    *,
    engagement_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AccreditationSummary], int]:
    rows, total = await repo.list_accreditations(
        session, org_id, engagement_id=engagement_id, limit=limit, offset=offset
    )
    return [AccreditationSummary.model_validate(r) for r in rows], total


async def transition(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    to_state: AccreditationState,
    actor: str,
    reason: str | None,
    *,
    triggered_by: str = "human",
    release_id: UUID | None = None,
    attestation_run_id: UUID | None = None,
) -> TransitionOut:
    acc = await repo.get_accreditation(session, org_id, accreditation_id)
    if acc is None:
        raise AccreditationNotFoundError(accreditation_id)

    from_state = acc.state
    if not transition_allowed(from_state, to_state.value):
        raise InvalidTransitionError(from_state, to_state.value)

    if to_state is AccreditationState.APPROVED and not approver_separation_ok(
        acc.submitted_by, actor
    ):
        raise SelfApprovalError("approver must differ from submitter")

    now = datetime.now(tz=UTC)
    updates: dict[str, Any] = {"state": to_state.value, "updated_at": now}

    if to_state is AccreditationState.SUBMITTED:
        updates.update({"submitted_by": actor, "submitted_at": now})
    elif to_state is AccreditationState.APPROVED:
        updates.update(
            {
                "approved_by": actor,
                "approved_at": now,
                "expires_at": now + timedelta(days=_APPROVAL_VALIDITY_DAYS),
                "next_attestation_due": now + timedelta(days=_DEFAULT_ATTESTATION_CADENCE_DAYS),
                "suspended_at": None,
                "suspension_reason": None,
                "suspended_by_release_id": None,
            }
        )
    elif to_state is AccreditationState.DRAFT and from_state == "submitted":
        updates.update({"submitted_by": None, "submitted_at": None})
    elif to_state is AccreditationState.SUSPENDED:
        updates.update(
            {
                "suspended_at": now,
                "suspension_reason": reason or "Suspended",
                "suspended_by_release_id": release_id,
            }
        )
    elif to_state is AccreditationState.EXPIRED:
        updates.update({"expires_at": now})
    elif to_state is AccreditationState.WITHDRAWN:
        updates.update({"withdrawn_at": now})

    updated = await repo.update_accreditation(session, org_id, accreditation_id, updates)
    assert updated is not None

    event_id = await evidence_service.record_one(
        session,
        org_id,
        EvidenceRecord(
            kind=EvidenceKind.ACCREDITATION_DECISION,
            occurred_at=now,
            agent_id=acc.agent_id,
            agent_version_id=acc.agent_version_id,
            engagement_id=acc.engagement_id,
            customer_id=acc.customer_id,
            actor=actor,
            action=f"accreditation_{to_state.value}",
            outcome=EvidenceOutcome.OBSERVED,
            subject_ref=acc.reference,
            detail={
                "from": from_state,
                "to": to_state.value,
                "reason": (reason or "")[:512],
            },
            detected_by=DetectedBy.COMPUTED,
        ),
    )

    trans = await repo.insert_transition(
        session,
        org_id,
        {
            "id": uuid4(),
            "accreditation_id": accreditation_id,
            "from_state": from_state,
            "to_state": to_state.value,
            "actor": actor,
            "reason": reason,
            "triggered_by": triggered_by,
            "release_id": release_id,
            "attestation_run_id": attestation_run_id,
            "evidence_event_id": event_id,
            "created_at": now,
        },
    )
    return TransitionOut.model_validate(trans)


async def submit_accreditation(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    payload: TransitionRequest,
) -> TransitionOut:
    return await transition(
        session,
        org_id,
        accreditation_id,
        AccreditationState.SUBMITTED,
        payload.actor,
        payload.reason,
    )


async def approve_accreditation(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    payload: TransitionRequest,
) -> TransitionOut:
    return await transition(
        session,
        org_id,
        accreditation_id,
        AccreditationState.APPROVED,
        payload.actor,
        payload.reason,
    )


async def reject_accreditation(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    payload: TransitionRequest,
) -> TransitionOut:
    return await transition(
        session,
        org_id,
        accreditation_id,
        AccreditationState.DRAFT,
        payload.actor,
        payload.reason,
    )


async def suspend_accreditation(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    payload: TransitionRequest,
) -> TransitionOut:
    return await transition(
        session,
        org_id,
        accreditation_id,
        AccreditationState.SUSPENDED,
        payload.actor,
        payload.reason,
    )


async def withdraw_accreditation(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    payload: TransitionRequest,
) -> TransitionOut:
    return await transition(
        session,
        org_id,
        accreditation_id,
        AccreditationState.WITHDRAWN,
        payload.actor,
        payload.reason,
    )


async def assemble_controls(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
) -> list[AccreditationControlOut]:
    acc = await repo.get_accreditation(session, org_id, accreditation_id)
    if acc is None:
        raise AccreditationNotFoundError(accreditation_id)

    await repo.delete_controls_for_accreditation(session, org_id, accreditation_id)
    controls = await repo.list_framework_controls(session, acc.framework_id)
    out: list[AccreditationControlOut] = []

    for control in controls:
        mappings = await repo.list_mappings_for_control(session, control.id)
        evidence_counts: dict[str, int] = {}
        for mapping in mappings:
            evidence_counts[mapping.evidence_kind] = await repo.count_evidence_for_agent_kind(
                session, org_id, acc.agent_id, mapping.evidence_kind
            )

        state, gap_reason, kinds, count = classify_control_answer(
            control.answer_mode,
            mappings,
            evidence_counts,
        )

        row = await repo.insert_accreditation_control(
            session,
            org_id,
            {
                "id": uuid4(),
                "accreditation_id": accreditation_id,
                "control_id": control.id,
                "state": state.value,
                "narrative": None,
                "evidence_kinds": kinds,
                "evidence_count": count,
                "gap_reason": gap_reason,
                "answered_at": datetime.now(tz=UTC)
                if state != ControlAnswerState.UNANSWERABLE
                else None,
                "answered_by": "service:accreditation",
            },
        )
        out.append(AccreditationControlOut.model_validate(row))
    return out


async def react_to_release(
    session: AsyncSession,
    org_id: UUID,
    release_id: UUID,
    assessment: DiffAssessment,
) -> list[TransitionOut]:
    """The 90-second demo: materiality impact drives accreditation state."""
    release = await repo.get_release(session, org_id, release_id)
    if release is None:
        raise AccreditationError(f"release {release_id} not found")

    if release.from_version_id is None:
        return []

    accreditations = await repo.list_live_accreditations_for_version(
        session,
        org_id,
        release.agent_id,
        release.from_version_id,
    )
    results: list[TransitionOut] = []

    primary_rule = assessment.rules_fired[0] if assessment.rules_fired else "materiality"

    if assessment.accreditation_impact is AccreditationImpact.SUSPENDS:
        for acc in accreditations:
            if acc.state != "approved":
                continue
            reason = f"Material release {release.release_tag}: rule {primary_rule}"
            results.append(
                await transition(
                    session,
                    org_id,
                    acc.id,
                    AccreditationState.SUSPENDED,
                    "service:materiality",
                    reason,
                    triggered_by="materiality",
                    release_id=release_id,
                )
            )
    elif assessment.accreditation_impact is AccreditationImpact.REQUIRES_REVALIDATION:
        due = datetime.now(tz=UTC)
        for acc in accreditations:
            if acc.state != "approved":
                continue
            await repo.update_accreditation(
                session,
                org_id,
                acc.id,
                {"next_attestation_due": due, "updated_at": due},
            )
    elif assessment.accreditation_impact is AccreditationImpact.NONE:
        await repo.advance_engagement_baseline(
            session,
            org_id,
            release.agent_id,
            release.from_version_id,
            release.to_version_id,
        )

    return results


async def render_pack(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    request: PackRenderRequest,
) -> AccreditationPackOut:
    acc = await repo.get_accreditation(session, org_id, accreditation_id)
    if acc is None:
        raise AccreditationNotFoundError(accreditation_id)

    requested_pdf = request.format == "pdf"
    pack_format = "json" if requested_pdf else request.format

    controls = await repo.list_accreditation_controls(session, org_id, accreditation_id)
    dossier = {
        "reference": acc.reference,
        "state": acc.state,
        "agent_id": str(acc.agent_id),
        "agent_version_id": str(acc.agent_version_id),
        "framework_id": str(acc.framework_id),
        "controls": [
            {
                "control_id": str(c.control_id),
                "state": c.state,
                "evidence_count": c.evidence_count,
            }
            for c in controls
        ],
        "rendered_at": datetime.now(tz=UTC).isoformat(),
    }
    if pack_format == "html":
        body = (
            f"<html><body><h1>{acc.reference}</h1><p>State: {acc.state}</p></body></html>"
        ).encode()
        content_type = "text/html"
        fmt = "html"
    else:
        body = json.dumps(dossier, sort_keys=True, separators=(",", ":")).encode()
        content_type = "application/json"
        fmt = "json"

    store = build_object_store()
    key = f"packs/{org_id}/{accreditation_id}/{fmt}/{uuid4()}.{'html' if fmt == 'html' else 'json'}"
    stored = store.put(key, body, content_type)
    signer = build_signer()
    signature = signer.sign(body)
    checkpoint_id = await repo.get_latest_checkpoint_id(session, org_id)

    await repo.demote_current_packs(session, org_id, accreditation_id, fmt)
    now = datetime.now(tz=UTC)
    pack = await repo.insert_pack(
        session,
        org_id,
        {
            "id": uuid4(),
            "accreditation_id": accreditation_id,
            "format": fmt,
            "pack_uri": stored.uri,
            "pack_digest": stored.digest,
            "byte_size": stored.size,
            "checkpoint_id": checkpoint_id,
            "signature": signature,
            "signing_key_ref": signer.key_id,
            "signed_at": now,
            "rendered_at": now,
            "rendered_by": request.rendered_by,
            "is_current": True,
        },
    )
    out = AccreditationPackOut.model_validate(pack)
    if requested_pdf:
        raise PackRenderError("PDF rendering via WeasyPrint is deferred; JSON pack stored instead")
    return out


async def list_controls(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> list[AccreditationControlOut]:
    rows = await repo.list_accreditation_controls(session, org_id, accreditation_id)
    return [AccreditationControlOut.model_validate(r) for r in rows]


async def list_packs(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> list[AccreditationPackOut]:
    rows = await repo.list_packs(session, org_id, accreditation_id)
    return [AccreditationPackOut.model_validate(r) for r in rows]


async def list_transition_history(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> list[TransitionOut]:
    rows = await repo.list_transitions(session, org_id, accreditation_id)
    return [TransitionOut.model_validate(r) for r in rows]


async def compute_readiness(
    session: AsyncSession,
    org_id: UUID,
    customer_id: UUID,
) -> ReadinessOut:
    """Per required framework: how much can we evidence for this client?"""
    frameworks = await repo.fetch_customer_frameworks(session, org_id, customer_id)
    framework_summaries: list[dict[str, object]] = []
    gaps: list[ReadinessGap] = []

    for framework, _cf in frameworks:
        controls = await repo.list_framework_controls(session, framework.id)
        answerable = 0
        for control in controls:
            mappings = await repo.list_mappings_for_control(session, control.id)
            state, gap_reason, _, _ = classify_control_answer(
                control.answer_mode,
                mappings,
                {},
            )
            if state in (
                ControlAnswerState.ANSWERED,
                ControlAnswerState.PARTIAL,
                ControlAnswerState.NARRATIVE,
            ):
                answerable += 1
            elif state is ControlAnswerState.UNANSWERABLE and gap_reason:
                gaps.append(
                    ReadinessGap(
                        framework_id=framework.id,
                        framework_slug=framework.slug,
                        control_ref=control.control_ref,
                        title=control.title,
                        gap_reason=gap_reason,
                    )
                )
        framework_summaries.append(
            {
                "framework_id": str(framework.id),
                "framework_slug": framework.slug,
                "controls_total": len(controls),
                "answerable": answerable,
            }
        )

    return ReadinessOut(customer_id=customer_id, frameworks=framework_summaries, gaps=gaps)
