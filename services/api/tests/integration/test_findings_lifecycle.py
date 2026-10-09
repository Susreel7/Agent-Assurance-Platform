"""Finding lifecycle against a real Postgres.

These run against a server because the thing under test is agreement between the service
layer and `findings_resolution_consistent`, the CHECK that ties `resolved_at` to exactly
the three resolved states. A mocked session records whatever dict it is handed and so
cannot fail; both defects below were invisible to unit tests and surfaced when the seed
generator drove real transitions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.assurance import service as assurance_svc
from app.domains.assurance.schemas import (
    FindingCategory,
    FindingCreate,
    FindingResolve,
    FindingSource,
    FindingState,
    FindingTriage,
    Severity,
)
from app.domains.registry import repository as registry_repo

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _agent(session: AsyncSession, org_id: uuid.UUID) -> Any:
    return await registry_repo.insert_agent(
        session,
        org_id,
        {
            "id": uuid.uuid4(),
            "urn": f"urn:aap:it:{uuid.uuid4().hex[:8]}:eu",
            "display_name": "Findings Agent",
            "lifecycle_state": "production",
        },
    )


def _create(agent_id: uuid.UUID, *, subject: str = "PI-01") -> FindingCreate:
    return FindingCreate(
        agent_id=agent_id,
        agent_version_id=None,
        source=FindingSource.PROBE,
        category=FindingCategory.PROMPT_INJECTION,
        severity=Severity.HIGH,
        title="Indirect injection via retrieved document",
        detail="Raised by the probe pipeline.",
        subject_ref=subject,
        remediation_due=datetime.now(tz=UTC) + timedelta(days=14),
    )


async def test_triaging_a_resolved_finding_clears_the_resolution(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The defect: triage set state without dropping `resolved_at`, so the row landed on
    the wrong side of the CHECK and Postgres refused the write as a 500."""
    agent = await _agent(session, org_id)
    finding = await assurance_svc.record_finding(session, org_id, _create(agent.id))

    resolved = await assurance_svc.resolve_finding(
        session,
        org_id,
        finding.id,
        FindingResolve(
            state=FindingState.FALSE_POSITIVE,
            resolved_by="person:reviewer@test.example",
            resolution_note="Probe matched a quoted example.",
        ),
    )
    assert resolved.resolved_at is not None

    reopened = await assurance_svc.triage_finding(
        session,
        org_id,
        finding.id,
        FindingTriage(
            triaged_by="person:reviewer@test.example",
            remediation_due=datetime.now(tz=UTC) + timedelta(days=7),
        ),
    )

    assert reopened.state is FindingState.TRIAGED
    assert reopened.resolved_at is None
    assert reopened.resolved_by is None


async def test_a_fixed_finding_seen_again_reopens(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Recurrence of something marked fixed is a regression, not a duplicate. Leaving it
    `fixed` while the probe still matches is the one reading that is certainly wrong."""
    agent = await _agent(session, org_id)
    first = await assurance_svc.record_finding(session, org_id, _create(agent.id))
    await assurance_svc.resolve_finding(
        session,
        org_id,
        first.id,
        FindingResolve(
            state=FindingState.FIXED,
            resolved_by="person:eng@test.example",
            resolution_note="Patched in 1.4.2.",
        ),
    )

    again = await assurance_svc.record_finding(session, org_id, _create(agent.id))

    assert again.id == first.id, "same fingerprint must not create a second row"
    assert again.state is FindingState.OPEN
    assert again.resolved_at is None
    assert again.resolution_note is None
    assert again.first_seen_at == first.first_seen_at, "first sighting is history"
    assert again.last_seen_at > first.last_seen_at


@pytest.mark.parametrize(
    "suppressed",
    [FindingState.FALSE_POSITIVE, FindingState.ACCEPTED],
)
async def test_suppressed_findings_stay_suppressed_when_seen_again(
    session: AsyncSession, org_id: uuid.UUID, suppressed: FindingState
) -> None:
    """The counterpart to the reopen rule. Both states record a human decision about a
    finding that recurs by its nature, and reopening them refills the queue with rows
    somebody already dismissed. See D-032."""
    agent = await _agent(session, org_id)
    first = await assurance_svc.record_finding(session, org_id, _create(agent.id))
    await assurance_svc.resolve_finding(
        session,
        org_id,
        first.id,
        FindingResolve(
            state=suppressed,
            resolved_by="person:risk@test.example",
            resolution_note="Accepted for this engagement.",
        ),
    )

    again = await assurance_svc.record_finding(session, org_id, _create(agent.id))

    assert again.id == first.id
    assert again.state is suppressed
    assert again.resolved_at is not None
    assert again.last_seen_at > first.last_seen_at, "recurrence is still recorded"


async def test_resighting_does_not_cross_tenants(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """Fingerprints are derived from agent and subject, not from the org, so the lookup
    that finds an existing finding has to be scoped or one tenant's probe result silently
    updates another's."""
    mine = await _agent(session, org_id)
    theirs = await _agent(session, other_org_id)

    a = await assurance_svc.record_finding(session, org_id, _create(mine.id))
    b = await assurance_svc.record_finding(session, other_org_id, _create(theirs.id))

    assert a.id != b.id
