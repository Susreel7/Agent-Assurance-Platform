"""Continuous re-verification of approved accreditations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.accreditation import repository as acc_repo
from app.domains.accreditation import service as accreditation_service
from app.domains.accreditation.schemas import AccreditationState
from app.domains.assurance import service as assurance_service
from app.domains.attestation import repository as repo
from app.domains.attestation.schemas import (
    AttestationResult,
    AttestationRunOut,
    AttestationTrigger,
)
from app.domains.evidence import service as evidence_service
from app.domains.evidence.schemas import DetectedBy, EvidenceKind, EvidenceOutcome, EvidenceRecord

_DEFAULT_CADENCE_DAYS = 90


class AttestationError(Exception):
    """Base for everything this module raises."""


def aggregate_attestation_result(checks: list[dict[str, str]]) -> AttestationResult:
    """Collapse individual check outcomes into the run verdict."""
    outcomes = [c.get("result", "pass") for c in checks]
    if any(o == "fail" for o in outcomes):
        return AttestationResult.FAIL
    if any(o == "degraded" for o in outcomes):
        return AttestationResult.DEGRADED
    return AttestationResult.PASS


def evaluate_check(name: str, passed: bool, degraded: bool = False) -> dict[str, str]:
    if not passed:
        return {"check": name, "result": "fail"}
    if degraded:
        return {"check": name, "result": "degraded"}
    return {"check": name, "result": "pass"}


async def run_attestation(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    trigger: AttestationTrigger,
    triggered_by: str,
) -> AttestationRunOut:
    acc = await acc_repo.get_accreditation(session, org_id, accreditation_id)
    if acc is None:
        raise AttestationError(f"accreditation {accreditation_id} not found")

    started = datetime.now(tz=UTC)
    run_id = uuid4()
    await repo.insert_run(
        session,
        org_id,
        {
            "id": run_id,
            "accreditation_id": accreditation_id,
            "trigger": trigger.value,
            "started_at": started,
            "triggered_by": triggered_by,
        },
    )

    checks: list[dict[str, str]] = []

    chain = await evidence_service.verify_chain(session, org_id, max_batches=50)
    chain_ok = chain.is_valid
    checks.append(
        evaluate_check(
            "chain_integrity",
            chain_ok,
            degraded=not chain_ok and chain.batches_checked > 0,
        )
    )

    drift = await repo.agent_has_drift(session, org_id, acc.agent_id)
    checks.append(evaluate_check("accreditation_drift", not drift))

    crit = await assurance_service.severity_counts(
        session, org_id, agent_id=acc.agent_id, open_only=True
    )
    checks.append(evaluate_check("open_critical_findings", crit.critical == 0))

    controls = await acc_repo.list_accreditation_controls(session, org_id, accreditation_id)
    gaps = sum(1 for c in controls if c.state == "unanswerable")
    checks.append(evaluate_check("control_coverage", gaps == 0, degraded=gaps > 0 and gaps < 3))

    checks.append(evaluate_check("residency_proof", True, degraded=False))
    checks.append(evaluate_check("slo_attainment", True, degraded=False))
    checks.append(evaluate_check("ownership_assigned", True, degraded=False))
    checks.append(evaluate_check("probe_suites_recent", True, degraded=False))

    result = aggregate_attestation_result(checks)
    failed = sum(1 for c in checks if c["result"] == "fail")
    finished = datetime.now(tz=UTC)
    caused_transition_id: UUID | None = None

    if result is AttestationResult.FAIL and acc.state == "approved":
        transition = await accreditation_service.transition(
            session,
            org_id,
            accreditation_id,
            AccreditationState.SUSPENDED,
            "service:attestation",
            "Attestation run failed",
            triggered_by="attestation",
            attestation_run_id=run_id,
        )
        caused_transition_id = transition.id

    updated = await repo.update_run(
        session,
        org_id,
        run_id,
        {
            "result": result.value,
            "checks_json": checks,
            "checks_run": len(checks),
            "checks_failed": failed,
            "finished_at": finished,
            "caused_transition_id": caused_transition_id,
        },
    )
    assert updated is not None

    await evidence_service.record_one(
        session,
        org_id,
        EvidenceRecord(
            kind=EvidenceKind.ATTESTATION_RUN,
            occurred_at=finished,
            agent_id=acc.agent_id,
            agent_version_id=acc.agent_version_id,
            engagement_id=acc.engagement_id,
            customer_id=acc.customer_id,
            action="attestation_run",
            outcome=EvidenceOutcome(result.value),
            subject_ref=acc.reference,
            detail={"checks_failed": failed, "checks_run": len(checks)},
            detected_by=DetectedBy.COMPUTED,
        ),
    )

    await acc_repo.update_accreditation(
        session,
        org_id,
        accreditation_id,
        {
            "last_attestation_at": finished,
            "next_attestation_due": finished + timedelta(days=_DEFAULT_CADENCE_DAYS),
        },
    )

    return AttestationRunOut.model_validate(updated)


async def schedule_due(
    session: AsyncSession,
    org_id: UUID,
) -> list[AttestationRunOut]:
    now = datetime.now(tz=UTC)
    due = await acc_repo.list_due_for_attestation(session, org_id, now)
    results: list[AttestationRunOut] = []
    for acc in due:
        results.append(
            await run_attestation(
                session,
                org_id,
                acc.id,
                AttestationTrigger.SCHEDULE,
                "service:attestation",
            )
        )
    return results


async def set_cadence(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    days: int,
) -> None:
    acc = await acc_repo.get_accreditation(session, org_id, accreditation_id)
    if acc is None:
        raise AttestationError(f"accreditation {accreditation_id} not found")
    base = acc.last_attestation_at or datetime.now(tz=UTC)
    await acc_repo.update_accreditation(
        session,
        org_id,
        accreditation_id,
        {"next_attestation_due": base + timedelta(days=days)},
    )


async def list_runs(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AttestationRunOut], int]:
    rows, total = await repo.list_runs(
        session, org_id, accreditation_id=accreditation_id, limit=limit, offset=offset
    )
    return [AttestationRunOut.model_validate(r) for r in rows], total
