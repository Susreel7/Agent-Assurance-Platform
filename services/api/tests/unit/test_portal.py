"""The portal's isolation filter, in isolation.

`scope_agents_to_engagement` is a pure function for one reason: it is the boundary
between two clients of the same consultancy, who share an `org_id` and therefore share
every other protection in the product. Tests that need a database do not get written for
edge cases; these do.

The engagement-level behaviour that needs real queries lives in
`tests/integration/test_portal.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.domains.portal.service import PortalError, scope_agents_to_engagement


@dataclass
class AgentRow:
    engagement_id: UUID
    agent_id: UUID


def test_second_engagement_agents_never_appear_in_first_view() -> None:
    engagement_a = uuid4()
    engagement_b = uuid4()
    agent_a = uuid4()
    agent_b = uuid4()

    rows_a = [AgentRow(engagement_a, agent_a)]
    rows_b = [AgentRow(engagement_b, agent_b)]

    scoped = scope_agents_to_engagement(rows_a, engagement_a, other_engagement_agents=rows_b)
    assert scoped == [agent_a]
    assert agent_b not in scoped


def test_rows_belonging_to_another_engagement_are_dropped() -> None:
    """The filter is given whatever the query returned. If a predicate is ever dropped
    upstream, this is the last thing standing between the two clients."""
    mine = uuid4()
    theirs = uuid4()
    my_agent = uuid4()
    their_agent = uuid4()

    scoped = scope_agents_to_engagement(
        [AgentRow(mine, my_agent), AgentRow(theirs, their_agent)],
        mine,
    )

    assert scoped == [my_agent]


def test_an_agent_in_scope_for_two_engagements_is_reported_not_silently_included() -> None:
    """One agent legitimately serving two clients is not a leak — but returning it
    without comment means the portal for client A lists an agent that also runs for
    client B, and nothing anywhere says so. The caller passes the other engagement's
    rows precisely to be told."""
    mine = uuid4()
    theirs = uuid4()
    shared = uuid4()

    with pytest.raises(PortalError) as caught:
        scope_agents_to_engagement(
            [AgentRow(mine, shared)],
            mine,
            other_engagement_agents=[AgentRow(theirs, shared)],
        )

    assert str(shared) in str(caught.value)


def test_the_leak_check_reports_every_agent_involved() -> None:
    """A single name would send someone to fix one row and re-run, finding the next."""
    mine = uuid4()
    theirs = uuid4()
    first, second = uuid4(), uuid4()

    with pytest.raises(PortalError) as caught:
        scope_agents_to_engagement(
            [AgentRow(mine, first), AgentRow(mine, second)],
            mine,
            other_engagement_agents=[AgentRow(theirs, first), AgentRow(theirs, second)],
        )

    message = str(caught.value)
    assert str(first) in message
    assert str(second) in message


def test_no_agents_in_scope_is_an_empty_list_not_an_error() -> None:
    """A new engagement has no agents yet. That is an ordinary state, and the portal
    should render an empty estate rather than fail."""
    assert scope_agents_to_engagement([], uuid4()) == []


def test_the_comparison_set_alone_does_not_add_agents() -> None:
    """`other_engagement_agents` is there to be checked against, never to contribute.
    If it ever became a second source of rows, one client's portal would list the
    other's estate — the exact failure the argument exists to detect."""
    mine = uuid4()
    theirs = uuid4()

    scoped = scope_agents_to_engagement(
        [],
        mine,
        other_engagement_agents=[AgentRow(theirs, uuid4()), AgentRow(theirs, uuid4())],
    )

    assert scoped == []


def test_duplicate_scope_rows_do_not_trip_the_leak_check() -> None:
    """The same agent scoped twice to the same engagement is a data oddity, not a
    cross-client leak, and must not raise — the portal would go down for one client
    over a duplicate row that harms nobody."""
    mine = uuid4()
    agent = uuid4()

    scoped = scope_agents_to_engagement(
        [AgentRow(mine, agent), AgentRow(mine, agent)],
        mine,
        other_engagement_agents=[AgentRow(uuid4(), uuid4())],
    )

    assert scoped == [agent, agent]
