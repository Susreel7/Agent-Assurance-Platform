"""Capability digests, and what counts as drift.

The digest is what makes a snapshot content-addressed: two discoveries that see the same
tools produce the same snapshot, and any change a decision depends on produces a different
one. Get this wrong in the permissive direction and a server can swap a tool's behaviour
without the registry noticing; get it wrong in the strict direction and reviewers learn to
click through drift banners, which is worse than not having them.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.domains.mcp_registry import service
from app.domains.mcp_registry.schemas import (
    CapabilityDeclared,
    CapabilityKind,
    GrantCreate,
    ServerRegister,
    Transport,
)
from app.domains.registry.schemas import LifecycleState


def _tool(
    name: str = "read_file",
    *,
    schema: str | None = "a" * 64,
    read_only: bool | None = True,
    destructive: bool | None = None,
    idempotent: bool | None = None,
    open_world: bool | None = None,
    title: str | None = None,
) -> CapabilityDeclared:
    return CapabilityDeclared(
        kind=CapabilityKind.TOOL,
        name=name,
        title=title,
        input_schema_digest=schema,
        declared_read_only=read_only,
        declared_destructive=destructive,
        declared_idempotent=idempotent,
        declared_open_world=open_world,
    )


# ---- what the digest covers -----------------------------------------------------------


def test_same_tools_in_a_different_order_are_one_snapshot() -> None:
    """MCP does not promise a stable ordering, so ordering must not read as drift."""
    forward = service.capability_digest([_tool("a"), _tool("b"), _tool("c")])
    shuffled = service.capability_digest([_tool("c"), _tool("a"), _tool("b")])
    assert forward == shuffled


def test_adding_a_tool_changes_the_digest() -> None:
    before = service.capability_digest([_tool("read_file")])
    after = service.capability_digest([_tool("read_file"), _tool("delete_file")])
    assert before != after


def test_removing_a_tool_changes_the_digest() -> None:
    before = service.capability_digest([_tool("read_file"), _tool("delete_file")])
    after = service.capability_digest([_tool("read_file")])
    assert before != after


def test_a_changed_input_schema_changes_the_digest() -> None:
    """The dangerous case: same name, different shape.

    A reviewed `read_file` that grows a `write_to` argument is a different tool wearing the
    reviewed one's name, and it is the substitution a name-only digest would miss.
    """
    before = service.capability_digest([_tool(schema="a" * 64)])
    after = service.capability_digest([_tool(schema="b" * 64)])
    assert before != after


@pytest.mark.parametrize(
    "field",
    ["read_only", "destructive", "idempotent", "open_world"],
)
def test_a_changed_annotation_changes_the_digest(field: str) -> None:
    """All four hints are covered, because each one a reviewer read is a claim to re-check."""
    before = service.capability_digest([_tool(**{field: True})])  # type: ignore[arg-type]
    after = service.capability_digest([_tool(**{field: False})])  # type: ignore[arg-type]
    assert before != after


def test_undeclared_is_not_the_same_as_declared_false() -> None:
    """ "The server did not say" and "the server said no" are different claims.

    Collapsing `None` into `False` would let a server go from silent to explicitly
    non-destructive without anybody being asked, and only the first state is grounds for
    asking in the first place.
    """
    silent = service.capability_digest([_tool(destructive=None)])
    denied = service.capability_digest([_tool(destructive=False)])
    claimed = service.capability_digest([_tool(destructive=True)])
    assert len({silent, denied, claimed}) == 3


def test_a_reworded_title_is_not_drift() -> None:
    """Titles are excluded deliberately.

    A server tidying up its human-readable descriptions has not changed what any tool can
    do, and treating that as drift trains reviewers to dismiss the banner.
    """
    before = service.capability_digest([_tool(title="Read a file")])
    after = service.capability_digest([_tool(title="Read file contents")])
    assert before == after


def test_a_tool_and_a_prompt_of_the_same_name_are_distinct() -> None:
    """Kind is part of the address: `search` the tool is not `search` the prompt."""
    as_tool = service.capability_digest([_tool("search")])
    as_prompt = service.capability_digest(
        [
            CapabilityDeclared(
                kind=CapabilityKind.PROMPT,
                name="search",
                input_schema_digest="a" * 64,
                declared_read_only=True,
            )
        ]
    )
    assert as_tool != as_prompt


def test_empty_capability_set_still_digests() -> None:
    """A server that offers nothing is a legitimate observation, not an error.

    It is also the state that should deny every call, and it needs an address to be stored
    against like any other.
    """
    assert len(service.capability_digest([])) == 32


def test_digest_is_a_sha256() -> None:
    assert len(service.capability_digest([_tool()])) == 32


# ---- registration shape ---------------------------------------------------------------


def test_http_transport_requires_an_endpoint() -> None:
    with pytest.raises(ValidationError):
        ServerRegister(
            slug="files",
            name="Files",
            transport=Transport.HTTP,
            environments=[LifecycleState.DEV],
        )


def test_stdio_transport_requires_a_command() -> None:
    """A stdio server with no command cannot be reached, so registering one is a mistake."""
    with pytest.raises(ValidationError):
        ServerRegister(
            slug="files",
            name="Files",
            transport=Transport.STDIO,
            environments=[LifecycleState.DEV],
        )


def test_registration_needs_at_least_one_environment() -> None:
    with pytest.raises(ValidationError):
        ServerRegister(
            slug="files",
            name="Files",
            transport=Transport.HTTP,
            endpoint_url="https://files.internal/mcp",
            environments=[],
        )


# ---- grant shape ----------------------------------------------------------------------


def test_grants_are_pinned_to_a_snapshot_by_default() -> None:
    """The default is what makes a newly added tool require a new decision.

    Without pinning, a server that adds a tool and gets re-approved hands that tool to every
    existing grant — approval would widen access nobody reviewed.
    """
    grant = GrantCreate(
        subject_kind="agent",
        subject_id=uuid.uuid4(),
        environments=[LifecycleState.PRODUCTION],
    )
    assert grant.pin_approved_snapshot is True


def test_a_grant_without_a_capability_name_covers_the_whole_server() -> None:
    grant = GrantCreate(
        subject_kind="agent",
        subject_id=uuid.uuid4(),
        environments=[LifecycleState.PRODUCTION],
    )
    assert grant.capability_name is None
    assert grant.permission == "invoke"


def test_grant_permission_is_a_closed_set() -> None:
    """`invoke` and `read`, not free text. An unknown verb would be checked by nothing."""
    with pytest.raises(ValidationError):
        GrantCreate(
            subject_kind="agent",
            subject_id=uuid.uuid4(),
            environments=[LifecycleState.PRODUCTION],
            permission="delete",
        )


def test_grant_subject_kind_is_a_closed_set() -> None:
    with pytest.raises(ValidationError):
        GrantCreate(
            subject_kind="anybody",
            subject_id=uuid.uuid4(),
            environments=[LifecycleState.PRODUCTION],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verified_write", "requires_approval"),
    [(False, False), (True, True)],
)
async def test_server_write_policy_applies_only_to_verified_writes(
    monkeypatch: pytest.MonkeyPatch,
    verified_write: bool,
    requires_approval: bool,
) -> None:
    server = SimpleNamespace(
        id=uuid.uuid4(),
        state="approved",
        approved_snapshot_id=uuid.uuid4(),
        environments=["production"],
        requires_approval_for_writes=True,
    )
    capability = SimpleNamespace(
        name="tool",
        verified_risk="medium",
        verified_write=verified_write,
    )
    grant = SimpleNamespace(id=uuid.uuid4(), requires_approval=False)
    monkeypatch.setattr(
        service.repo,
        "decide_tool_call",
        AsyncMock(return_value=(server, capability, grant)),
    )

    decision = await service.decide(
        AsyncMock(),
        uuid.uuid4(),
        server_slug="server",
        capability_name="tool",
        subjects=[("agent", uuid.uuid4())],
        environment="production",
    )

    assert decision.allowed is True
    assert decision.requires_approval is requires_approval
