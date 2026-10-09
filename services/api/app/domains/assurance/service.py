"""Findings, probe runs and posture scoring.

Posture exists so a security reviewer can ask "how bad is it right now?" without reading
every queue. The score is deliberately meaningless without its contributors — the
migration enforces that — because a single number without factors gets quoted out of
context in executive slides.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.assurance import repository as repo
from app.domains.assurance.probe_executor import (
    ProbeRolloutRequest,
    default_probe_target,
)
from app.domains.assurance.probe_oracle import (
    JudgeAdvisory,
    JudgeVerdict,
    OracleResult,
    OracleVerdict,
    advisory_judge_from_oracle,
    apply_judge_advisory,
    evaluate_assertions,
    probe_run_gate_result,
    suite_content_digest,
)
from app.domains.assurance.rule_gaps import (
    RuleGapReport,
    build_rule_gap_report,
    export_rule_gaps_markdown,
)
from app.domains.assurance.schemas import (
    _RESOLVED_STATES,
    AgentProbeStatusOut,
    FindingCategory,
    FindingCreate,
    FindingOut,
    FindingPage,
    FindingResolve,
    FindingSource,
    FindingState,
    FindingTriage,
    JudgeAdvisoryOut,
    PostureContributor,
    PostureInputs,
    PostureScoreOut,
    ProbeCaseResultOut,
    ProbeRunDetailOut,
    ProbeRunOut,
    ProbeRunSummaryOut,
    ProbeStatusEntry,
    ProbeSuiteOut,
    Severity,
    SeverityCounts,
)
from app.domains.composition import service as composition_svc
from app.domains.composition.schemas import (
    CompositionElementKind,
    CompositionElementOut,
    ReconciliationStatus,
)
from app.domains.evidence import service as evidence_service
from app.domains.evidence.schemas import DetectedBy, EvidenceKind, EvidenceOutcome, EvidenceRecord
from app.domains.registry import service as registry_svc

# Posture deduction weights — conservative so one critical finding cannot be drowned out.
_CRITICAL_FINDING_POINTS = 15
_HIGH_FINDING_POINTS = 8
_SUSPENSION_POINTS = 30
_DRIFT_POINTS = 20
_OVERDUE_POINTS = 10
_UNMAPPED_CONTROL_POINTS = 5
_OWNERSHIP_POINTS = 15
_UNOBSERVED_EDGE_POINTS = 5

_CAP_CRITICAL = 45
_CAP_HIGH = 24
_CAP_OVERDUE = 20
_CAP_UNMAPPED = 15
_CAP_EDGES = 15


class AssuranceError(Exception):
    """Base for everything this module raises."""


class FindingNotFoundError(AssuranceError):
    def __init__(self, finding_id: UUID) -> None:
        super().__init__(f"finding {finding_id} not found")
        self.finding_id = finding_id


class ProbeSuiteNotFoundError(AssuranceError):
    def __init__(self, suite_id: UUID) -> None:
        super().__init__(f"probe suite {suite_id} not found")
        self.suite_id = suite_id


class ProbeRunNotFoundError(AssuranceError):
    def __init__(self, run_id: UUID) -> None:
        super().__init__(f"probe run {run_id} not found")
        self.run_id = run_id


class InvalidResolutionError(AssuranceError):
    pass


def finding_fingerprint(
    source: str,
    category: str,
    agent_id: UUID | None,
    subject_ref: str | None,
) -> str:
    """Stable dedup key — without it every rescan opens a duplicate triage item."""
    payload = "|".join(
        [
            source,
            category,
            str(agent_id) if agent_id else "",
            subject_ref or "",
        ]
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolution_consistent(state: FindingState, resolved_at: datetime | None) -> bool:
    """Mirrors ``findings_resolution_consistent`` so invalid pairs fail before SQL."""
    needs_resolved = state in _RESOLVED_STATES
    return needs_resolved == (resolved_at is not None)


def score_to_band(score: int) -> str:
    if score >= 85:
        return "strong"
    if score >= 70:
        return "adequate"
    if score >= 50:
        return "weak"
    return "critical"


def compute_posture_arithmetic(inputs: PostureInputs) -> tuple[int, list[PostureContributor]]:
    """Pure posture math — the database layer supplies the input counts."""
    contributors: list[PostureContributor] = [
        PostureContributor(factor="baseline", points=0, detail="Starting score before deductions")
    ]
    score = 100

    if inputs.open_critical_count:
        pts = min(
            inputs.open_critical_count * _CRITICAL_FINDING_POINTS,
            _CAP_CRITICAL,
        )
        score -= pts
        contributors.append(
            PostureContributor(
                factor="open_critical_findings",
                points=-pts,
                detail=f"{inputs.open_critical_count} open critical finding(s)",
            )
        )

    if inputs.open_high_count:
        pts = min(inputs.open_high_count * _HIGH_FINDING_POINTS, _CAP_HIGH)
        score -= pts
        contributors.append(
            PostureContributor(
                factor="open_high_findings",
                points=-pts,
                detail=f"{inputs.open_high_count} open high finding(s)",
            )
        )

    if inputs.accreditation_suspended:
        score -= _SUSPENSION_POINTS
        contributors.append(
            PostureContributor(
                factor="accreditation_suspended",
                points=-_SUSPENSION_POINTS,
                detail="An approved accreditation is currently suspended",
            )
        )

    if inputs.accreditation_drift:
        score -= _DRIFT_POINTS
        contributors.append(
            PostureContributor(
                factor="accreditation_drift",
                points=-_DRIFT_POINTS,
                detail="Deployed version differs from the accredited baseline",
            )
        )

    if inputs.overdue_remediation_count:
        pts = min(inputs.overdue_remediation_count * _OVERDUE_POINTS, _CAP_OVERDUE)
        score -= pts
        contributors.append(
            PostureContributor(
                factor="overdue_remediation",
                points=-pts,
                detail=f"{inputs.overdue_remediation_count} finding(s) past remediation due",
            )
        )

    if inputs.unmapped_control_count:
        pts = min(inputs.unmapped_control_count * _UNMAPPED_CONTROL_POINTS, _CAP_UNMAPPED)
        score -= pts
        contributors.append(
            PostureContributor(
                factor="unmapped_controls",
                points=-pts,
                detail=(
                    f"{inputs.unmapped_control_count} in-scope control(s) without evidence mapping"
                ),
            )
        )

    if inputs.missing_ownership:
        score -= _OWNERSHIP_POINTS
        contributors.append(
            PostureContributor(
                factor="missing_ownership",
                points=-_OWNERSHIP_POINTS,
                detail="No current ownership record for this agent",
            )
        )

    if inputs.declared_not_observed_edge_count:
        pts = min(
            inputs.declared_not_observed_edge_count * _UNOBSERVED_EDGE_POINTS,
            _CAP_EDGES,
        )
        score -= pts
        contributors.append(
            PostureContributor(
                factor="declared_not_observed_edges",
                points=-pts,
                detail=(
                    f"{inputs.declared_not_observed_edge_count} declared graph edge(s) "
                    "never observed in telemetry"
                ),
            )
        )

    score = max(0, min(100, score))
    if len(contributors) == 1:
        contributors.append(
            PostureContributor(
                factor="no_deductions",
                points=0,
                detail="No posture deductions applied",
            )
        )
    return score, contributors


def simulate_probe_pass(probe_id: str, agent_id: UUID) -> bool:
    """Deterministic pass/fail so demos replay without storing response bodies."""
    seed = f"{probe_id}:{agent_id}".encode()
    digest = hashlib.sha256(seed).digest()
    return digest[0] % 5 != 0


def _row_to_finding(row: object) -> FindingOut:
    return FindingOut.model_validate(row)


async def record_finding(
    session: AsyncSession,
    org_id: UUID,
    payload: FindingCreate,
) -> FindingOut:
    fp = finding_fingerprint(
        payload.source.value,
        payload.category.value,
        payload.agent_id,
        payload.subject_ref,
    )
    existing = await repo.get_finding_by_fingerprint(session, org_id, fp)
    now = datetime.now(tz=UTC)
    if existing is not None:
        resighting: dict[str, Any] = {"last_seen_at": now}
        # A finding marked `fixed` that the pipeline raises again has regressed, and
        # saying it is fixed while the probe still matches it is the one reading that is
        # certainly wrong. So recurrence reopens it and drops the stale resolution.
        #
        # `false_positive` and `accepted` are treated as suppressions and left alone. Both
        # record a human judgement about a finding that will keep recurring by its nature
        # -- the probe matches the same quoted example on every run -- and reopening them
        # would refill the queue with the exact rows somebody already dismissed. That is
        # how the queue stops being read. See D-032.
        if existing.state == FindingState.FIXED.value:
            resighting.update(
                {
                    "state": FindingState.OPEN.value,
                    "resolved_by": None,
                    "resolved_at": None,
                    "resolution_note": None,
                }
            )
            if payload.remediation_due is not None:
                resighting["remediation_due"] = payload.remediation_due
        updated = await repo.update_finding(session, org_id, existing.id, resighting)
        assert updated is not None
        return _row_to_finding(updated)

    values: dict[str, Any] = {
        "id": uuid4(),
        "agent_id": payload.agent_id,
        "agent_version_id": payload.agent_version_id,
        "source": payload.source.value,
        "category": payload.category.value,
        "severity": payload.severity.value,
        "title": payload.title,
        "detail": payload.detail,
        "subject_ref": payload.subject_ref,
        "fingerprint": fp,
        "state": FindingState.OPEN.value,
        "cve_id": payload.cve_id,
        "probe_run_id": payload.probe_run_id,
        "release_id": payload.release_id,
        "first_seen_at": now,
        "last_seen_at": now,
        "remediation_due": payload.remediation_due,
    }
    row = await repo.insert_finding(session, org_id, values)
    return _row_to_finding(row)


async def record_reconciliation_findings(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    version_id: UUID,
    elements: list[CompositionElementOut],
) -> None:
    """Persist drift findings from composition reconciliation.

    Lives in assurance rather than composition so reconciliation can stay left of
    findings in the domain chain — composition compares declared vs observed; assurance
    owns the finding queue they feed.
    """
    for el in elements:
        if el.status not in (
            ReconciliationStatus.OBSERVED_ONLY,
            ReconciliationStatus.CONFLICT,
        ):
            continue
        title = (
            f"Undeclared {el.kind.value.replace('_', ' ')}: {el.key}"
            if el.status == ReconciliationStatus.OBSERVED_ONLY
            else f"Model outside policy: {el.key}"
        )
        detail = (
            f"Observed {el.observed_count} time(s) in the reconciliation window "
            f"but not declared on version {version_id}."
        )
        subject = f"composition:{agent_id}:{el.kind.value}:{el.key}"
        await record_finding(
            session,
            org_id,
            FindingCreate(
                agent_id=agent_id,
                agent_version_id=version_id,
                source=FindingSource.DRIFT,
                category=FindingCategory.UNDECLARED_CAPABILITY,
                severity=(
                    Severity.HIGH if el.kind == CompositionElementKind.MODEL else Severity.MEDIUM
                ),
                title=title[:256],
                detail=detail[:512],
                subject_ref=subject[:512],
            ),
        )


async def triage_finding(
    session: AsyncSession,
    org_id: UUID,
    finding_id: UUID,
    payload: FindingTriage,
) -> FindingOut:
    row = await repo.get_finding(session, org_id, finding_id)
    if row is None:
        raise FindingNotFoundError(finding_id)
    now = datetime.now(tz=UTC)
    updated = await repo.update_finding(
        session,
        org_id,
        finding_id,
        {
            "state": FindingState.TRIAGED.value,
            "triaged_by": payload.triaged_by,
            "triaged_at": now,
            "remediation_due": payload.remediation_due,
            # Triage is a move back to an unresolved state, so the resolution has to go
            # with it. `findings_resolution_consistent` ties `resolved_at` to exactly the
            # three resolved states, and leaving it set here put the row on the wrong side
            # of that check: triaging anything already closed raised a 500 from the
            # database rather than a validation error. `resolve_finding` already clears
            # these when it moves the other way; this is the missing half of that pair.
            "resolved_by": None,
            "resolved_at": None,
            "resolution_note": None,
        },
    )
    assert updated is not None
    return _row_to_finding(updated)


async def resolve_finding(
    session: AsyncSession,
    org_id: UUID,
    finding_id: UUID,
    payload: FindingResolve,
) -> FindingOut:
    resolved_at = datetime.now(tz=UTC) if payload.state in _RESOLVED_STATES else None
    if not resolution_consistent(payload.state, resolved_at):
        raise InvalidResolutionError(
            "resolved_at must be set exactly when state is fixed, false_positive or accepted"
        )

    row = await repo.get_finding(session, org_id, finding_id)
    if row is None:
        raise FindingNotFoundError(finding_id)

    values: dict[str, Any] = {
        "state": payload.state.value,
        "resolved_by": payload.resolved_by if payload.state in _RESOLVED_STATES else None,
        "resolved_at": resolved_at,
        "resolution_note": payload.resolution_note,
    }
    if payload.state not in _RESOLVED_STATES:
        values["resolved_by"] = None
        values["resolved_at"] = None

    updated = await repo.update_finding(session, org_id, finding_id, values)
    assert updated is not None
    return _row_to_finding(updated)


async def list_findings(
    session: AsyncSession,
    org_id: UUID,
    *,
    severity: list[str] | None = None,
    source: list[str] | None = None,
    category: list[str] | None = None,
    state: list[str] | None = None,
    agent_id: UUID | None = None,
    overdue_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> FindingPage:
    rows, total = await repo.list_findings(
        session,
        org_id,
        severity=severity,
        source=source,
        category=category,
        state=state,
        agent_id=agent_id,
        overdue_only=overdue_only,
        limit=limit,
        offset=offset,
    )
    return FindingPage(
        items=[_row_to_finding(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def severity_counts(
    session: AsyncSession,
    org_id: UUID,
    *,
    agent_id: UUID | None = None,
    open_only: bool = True,
) -> SeverityCounts:
    raw = await repo.fetch_severity_counts(session, org_id, agent_id=agent_id, open_only=open_only)
    return SeverityCounts(**raw)


def _owasp_coverage(probes: list[dict[str, Any]]) -> list[str]:
    tags: set[str] = set()
    for probe in probes:
        tag = probe.get("owasp_agentic")
        if isinstance(tag, str):
            tags.add(tag)
    return sorted(tags)


async def list_probe_suites(session: AsyncSession, org_id: UUID) -> list[ProbeSuiteOut]:
    rows = await repo.list_probe_suites(session, org_id)
    out: list[ProbeSuiteOut] = []
    for row in rows:
        probes = list(row.probes_json or [])
        digest = row.content_digest or suite_content_digest(probes)
        if row.content_digest != digest:
            await repo.update_probe_suite_digest(session, row.id, digest)
        out.append(
            ProbeSuiteOut(
                id=row.id,
                slug=row.slug,
                name=row.name,
                category=FindingCategory(row.category),
                probe_count=row.probe_count,
                cadence=row.cadence,
                is_builtin=row.is_builtin,
                content_digest=digest,
                owasp_coverage=_owasp_coverage(probes),
            )
        )
    return out


def _maybe_advisory_judge(oracle: OracleResult, *, enabled: bool) -> JudgeAdvisory | None:
    if not enabled:
        return advisory_judge_from_oracle(oracle)
    if oracle.verdict is not OracleVerdict.NEEDS_REVIEW:
        return None
    # Stub judge never awards pass on ambiguous — records unclear only.
    return JudgeAdvisory(
        verdict=JudgeVerdict.UNCLEAR,
        disagrees_with_oracle=False,
    )


async def run_probe_suite(
    session: AsyncSession,
    org_id: UUID,
    suite_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID,
    triggered_by: str,
    *,
    extra_probes: tuple[dict[str, Any], ...] = (),
) -> ProbeRunOut:
    suite = await repo.get_probe_suite(session, org_id, suite_id)
    if suite is None:
        raise ProbeSuiteNotFoundError(suite_id)

    settings = get_settings()
    probes: list[dict[str, Any]] = [*list(suite.probes_json or []), *extra_probes]
    digest = suite.content_digest or suite_content_digest(probes)
    if suite.content_digest != digest:
        await repo.update_probe_suite_digest(session, suite.id, digest)

    target = default_probe_target()
    started = datetime.now(tz=UTC)
    results: list[dict[str, Any]] = []
    exec_pass = 0
    exec_fail = 0
    judge_pass = 0
    judge_fail = 0
    needs_review = 0
    disagreements = 0
    gate_passed_count = 0
    valid_rollouts = 0
    attempt_budget = 0

    for probe in probes:
        probe_id = str(probe.get("id", "unknown"))
        setup = probe.get("setup") or {}
        fixture_profile = str(setup.get("fixture_profile", "compliant_refuse"))
        turns = int(probe.get("turns") or 1)
        attempt_budget += max(1, turns)

        receipt = None
        for attempt in range(1, turns + 1):
            receipt = await target.execute_rollout(
                ProbeRolloutRequest(
                    probe_id=probe_id,
                    agent_id=agent_id,
                    agent_version_id=agent_version_id,
                    fixture_profile=fixture_profile,
                    attempt=attempt,
                )
            )
            if receipt.valid:
                valid_rollouts += 1

        assert receipt is not None
        oracle = evaluate_assertions(probe, receipt.observation)
        judge = _maybe_advisory_judge(oracle, enabled=settings.probe_llm_judge_enabled)
        combined = apply_judge_advisory(oracle, judge)
        combined = combined.model_copy(
            update={
                "probe_id": probe_id,
                "expect": str(probe.get("expect", "")),
            }
        )

        if combined.execution_verified and combined.oracle_passed:
            exec_pass += 1
        elif combined.execution_verified and not combined.oracle_passed:
            exec_fail += 1
        if combined.oracle_verdict is OracleVerdict.NEEDS_REVIEW:
            needs_review += 1
        if combined.judge_advisory is not None:
            if combined.judge_advisory.verdict is JudgeVerdict.PASS:
                judge_pass += 1
            elif combined.judge_advisory.verdict is JudgeVerdict.FAIL:
                judge_fail += 1
            if combined.judge_advisory.disagrees_with_oracle:
                disagreements += 1

        if combined.gate_passed:
            gate_passed_count += 1
        else:
            if combined.oracle_verdict is OracleVerdict.FAIL:
                fp = f"probe:{suite.slug}:{probe_id}"
                await record_finding(
                    session,
                    org_id,
                    FindingCreate(
                        agent_id=agent_id,
                        agent_version_id=agent_version_id,
                        source=FindingSource.PROBE,
                        category=FindingCategory(suite.category),
                        severity=Severity.HIGH,
                        title=f"Probe {probe_id} failed (oracle)",
                        subject_ref=fp,
                    ),
                )

        row = combined.model_dump(mode="json")
        if combined.judge_advisory is not None:
            row["judge_advisory"] = combined.judge_advisory.model_dump(mode="json")
        results.append(row)

    gate_level = settings.probe_gate_level
    if settings.probe_llm_gate and settings.probe_llm_judge_enabled:
        gate_level = "blocking"
    overall, blocks = probe_run_gate_result(
        oracle_failures=exec_fail,
        needs_review=needs_review,
        gate_level=gate_level,  # type: ignore[arg-type]
    )
    if gate_level == "advisory":
        blocks = False

    summary = {
        "suite_content_digest": digest,
        "valid_rollouts": valid_rollouts,
        "attempt_budget": attempt_budget,
        "execution_verified_pass": exec_pass,
        "execution_verified_fail": exec_fail,
        "judge_advisory_pass": judge_pass,
        "judge_advisory_fail": judge_fail,
        "oracle_needs_review": needs_review,
        "judge_oracle_disagreements": disagreements,
        "gate_level": gate_level,
        "gate_blocks_release": blocks,
    }

    finished = datetime.now(tz=UTC)
    run = await repo.insert_probe_run(
        session,
        org_id,
        {
            "id": uuid4(),
            "suite_id": suite_id,
            "agent_id": agent_id,
            "agent_version_id": agent_version_id,
            "started_at": started,
            "finished_at": finished,
            "result": overall,
            "probes_run": len(probes),
            "probes_passed": gate_passed_count,
            "probes_failed": len(probes) - gate_passed_count,
            "results_json": results,
            "summary_json": summary,
            "triggered_by": triggered_by,
        },
    )

    await evidence_service.record_one(
        session,
        org_id,
        EvidenceRecord(
            kind=EvidenceKind.ADVERSARIAL_PROBE,
            occurred_at=finished,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            action="probe_suite_run",
            outcome=(
                EvidenceOutcome.PASS
                if exec_fail == 0 and needs_review == 0
                else EvidenceOutcome.FAIL
            ),
            subject_ref=suite.slug,
            detail={
                "suite_id": str(suite_id),
                "execution_verified_fail": exec_fail,
                "oracle_needs_review": needs_review,
                "suite_content_digest": digest,
            },
            detected_by=DetectedBy.PROBE,
        ),
    )
    return ProbeRunOut.model_validate(run)


def _parse_probe_result(row: dict[str, Any]) -> ProbeCaseResultOut:
    judge_raw = row.get("judge_advisory")
    judge = JudgeAdvisoryOut.model_validate(judge_raw) if judge_raw else None
    return ProbeCaseResultOut(
        probe_id=str(row.get("probe_id", "")),
        expect=str(row.get("expect", "")),
        oracle_verdict=str(row.get("oracle_verdict", row.get("passed", ""))),
        oracle_passed=bool(row.get("oracle_passed", row.get("passed", False))),
        execution_verified=bool(row.get("execution_verified", False)),
        gate_passed=bool(row.get("gate_passed", row.get("passed", False))),
        judge_advisory=judge,
        recognition_execution_gap=bool(row.get("recognition_execution_gap", False)),
        response_digest=str(row.get("response_digest", "")),
        signals=dict(row.get("signals") or {}),
        ambiguous=bool(row.get("ambiguous", False)),
    )


async def get_probe_run_detail(
    session: AsyncSession,
    org_id: UUID,
    run_id: UUID,
) -> ProbeRunDetailOut:
    pair = await repo.get_probe_run_with_suite(session, org_id, run_id)
    if pair is None:
        raise ProbeRunNotFoundError(run_id)
    run, suite = pair
    summary_raw = dict(run.summary_json or {})
    summary = ProbeRunSummaryOut.model_validate(summary_raw) if summary_raw else None
    results = [_parse_probe_result(dict(r)) for r in list(run.results_json or [])]
    base = ProbeRunOut.model_validate(run)
    return ProbeRunDetailOut(
        **base.model_dump(),
        results=results,
        summary=summary,
        suite_slug=suite.slug,
    )


async def get_agent_probe_status(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID,
) -> AgentProbeStatusOut:
    suites = await repo.list_probe_suites(session, org_id)
    entries: list[ProbeStatusEntry] = []
    for suite in suites:
        last = await repo.fetch_latest_probe_run_for_suite(
            session, org_id, agent_version_id, suite.id
        )
        entries.append(
            ProbeStatusEntry(
                suite_slug=suite.slug,
                suite_name=suite.name,
                last_run_id=last.id if last else None,
                last_result=last.result if last else None,
                last_started_at=last.started_at if last else None,
                stale=last is None,
                gate_required=suite.cadence == "on_change",
            )
        )
    return AgentProbeStatusOut(
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        suites=entries,
    )


async def compute_rule_gaps(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID,
    *,
    framework_slug: str | None = None,
) -> RuleGapReport:
    await registry_svc.get_version_descriptor(session, org_id, agent_version_id)
    composition = await composition_svc.get_composition_summary(
        session, org_id, agent_id, agent_version_id, window_days=7
    )
    obligations = [o.model_dump() for o in composition.rule_obligations]
    required = await repo.fetch_obligation_requirements(
        session, org_id, agent_id, framework_slug=framework_slug
    )
    slugs = sorted({str(r["framework_slug"]) for r in required})
    return build_rule_gap_report(
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        framework_slugs=slugs,
        required_rows=required,
        obligations=obligations,
    )


async def export_rule_gaps(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID,
    *,
    framework_slug: str | None = None,
) -> str:
    report = await compute_rule_gaps(
        session, org_id, agent_id, agent_version_id, framework_slug=framework_slug
    )
    return export_rule_gaps_markdown(report)


async def compute_posture(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
) -> PostureScoreOut:
    inputs = await repo.fetch_posture_inputs(session, org_id, agent_id)
    score, contributors = compute_posture_arithmetic(PostureInputs.model_validate(inputs))
    band = score_to_band(score)
    version_id = await repo.fetch_deployed_version_id(session, org_id, agent_id)
    row = await repo.insert_posture_score(
        session,
        org_id,
        {
            "id": uuid4(),
            "agent_id": agent_id,
            "agent_version_id": version_id,
            "score": score,
            "band": band,
            "contributors": [c.model_dump() for c in contributors],
            "computed_at": datetime.now(tz=UTC),
            "ruleset": "default",
        },
    )
    return PostureScoreOut(
        id=row.id,
        agent_id=row.agent_id,
        agent_version_id=row.agent_version_id,
        score=row.score,
        band=row.band,
        contributors=contributors,
        computed_at=row.computed_at,
        ruleset=row.ruleset,
    )


async def get_latest_posture(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
) -> PostureScoreOut | None:
    row = await repo.get_latest_posture_score(session, org_id, agent_id)
    if row is None:
        return None
    contributors = [PostureContributor.model_validate(c) for c in row.contributors]
    return PostureScoreOut(
        id=row.id,
        agent_id=row.agent_id,
        agent_version_id=row.agent_version_id,
        score=row.score,
        band=row.band,
        contributors=contributors,
        computed_at=row.computed_at,
        ruleset=row.ruleset,
    )


async def list_probe_runs(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ProbeRunOut], int]:
    rows, total = await repo.list_probe_runs(
        session, org_id, agent_id=agent_id, limit=limit, offset=offset
    )
    return [ProbeRunOut.model_validate(r) for r in rows], total
