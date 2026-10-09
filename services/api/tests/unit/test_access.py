"""Authorization: what a permission set actually permits.

`EffectiveAccess.allows` runs on every guarded request, so its semantics are the closest
thing this product has to a load-bearing one-liner. The cases below are the ones that would
silently over- or under-permit if the flattening were wrong.

Everything here is pure: no session, no database. That is deliberate — an authorization rule
that can only be tested against Postgres is a rule nobody tests.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.access import service
from app.domains.access.schemas import (
    PERMISSIONS,
    AccessRequestCreate,
    EffectiveAccess,
    GrantCreate,
    RoleCreate,
    ScopeKind,
    SubjectKind,
)

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0017_account_access_registry.py"
)


def _access(scoped: dict[str, list[str]]) -> EffectiveAccess:
    return EffectiveAccess(
        member_id=uuid.uuid4(),
        role_keys=["engineer"],
        permissions=sorted(scoped),
        scoped=scoped,
    )


# ---- allows() -------------------------------------------------------------------------


def test_permission_held_at_a_scope_applies_at_that_scope() -> None:
    project = uuid.uuid4()
    access = _access({"mcp:grant": [f"project:{project}"]})
    assert access.allows("mcp:grant", f"project:{project}")


def test_permission_held_at_one_scope_does_not_reach_another() -> None:
    """The case that makes scoped grants worth having at all."""
    access = _access({"mcp:grant": [f"project:{uuid.uuid4()}"]})
    assert not access.allows("mcp:grant", f"project:{uuid.uuid4()}")


def test_account_scope_subsumes_every_narrower_scope() -> None:
    """A security admin granted at account level answers a page-out without a project grant.

    Deliberate asymmetry, and the reason `allows` cannot just be a set membership test.
    """
    access = _access({"audit:read": ["account"]})
    assert access.allows("audit:read", f"project:{uuid.uuid4()}")
    assert access.allows("audit:read", f"agent:{uuid.uuid4()}")
    assert access.allows("audit:read")


def test_narrow_scope_does_not_imply_account_scope() -> None:
    """The inverse must not hold: a project approver is not an account approver."""
    project = uuid.uuid4()
    access = _access({"access:approve": [f"project:{project}"]})
    assert access.allows("access:approve", f"project:{project}")
    assert not access.allows("access:approve")


def test_unheld_permission_is_denied_rather_than_defaulted() -> None:
    access = _access({"member:read": ["account"]})
    assert not access.allows("member:write")
    assert not access.allows("this:permission:does:not:exist")


def test_empty_access_permits_nothing() -> None:
    """An invited member with no grant can sign in and do nothing. That is the design."""
    access = EffectiveAccess(member_id=uuid.uuid4(), role_keys=[], permissions=[], scoped={})
    for permission in PERMISSIONS:
        assert not access.allows(permission)


def test_scope_key_matches_the_form_allows_compares_against() -> None:
    """`scope_key` and `allows` must agree, or every scoped grant silently fails closed."""
    project = uuid.uuid4()
    key = service.scope_key_for(ScopeKind.PROJECT, project)
    assert key == f"project:{project}"
    assert _access({"mcp:read": [key]}).allows("mcp:read", key)

    assert service.scope_key_for(ScopeKind.ACCOUNT, None) == "account"


# ---- role definitions -----------------------------------------------------------------


def test_role_cannot_carry_a_permission_that_does_not_exist() -> None:
    """Caught at definition, not at enforcement.

    A typo in a permission string would otherwise produce a role that looks right in the
    console and grants nothing, and the symptom would surface as a 403 somewhere else.
    """
    with pytest.raises(ValidationError, match="unknown permissions"):
        RoleCreate(
            key="incident_responder",
            name="Incident responder",
            description="Reads everything during an incident.",
            permissions=["audit:read", "audit:reed"],
            assignable_scopes=[ScopeKind.ACCOUNT],
        )


def test_role_permissions_are_deduplicated_and_ordered() -> None:
    role = RoleCreate(
        key="reader",
        name="Reader",
        description="Reads.",
        permissions=["mcp:read", "audit:read", "mcp:read"],
        assignable_scopes=[ScopeKind.ACCOUNT],
    )
    assert role.permissions == ["audit:read", "mcp:read"]


def test_role_key_must_be_a_stable_identifier() -> None:
    with pytest.raises(ValidationError):
        RoleCreate(
            key="Incident Responder",
            name="Incident responder",
            description="Reads.",
            permissions=["audit:read"],
            assignable_scopes=[ScopeKind.ACCOUNT],
        )


def test_every_seeded_builtin_permission_is_a_real_permission() -> None:
    """The migration seeds built-in roles as literal strings; nothing type-checks them.

    A permission seeded here but absent from `PERMISSIONS` would give a customer a role
    that grants something the guards never ask about — invisible until an audit.
    """
    source = MIGRATION.read_text(encoding="utf-8")
    seeded = {
        value
        for value in re.findall(r"[\"']([a-z_]+:[a-z_:]+)[\"']", source)
        # Colon-separated strings that are not permissions: connection URIs and the like.
        if not value.startswith(("http", "postgresql", "vault"))
    }

    # Guards against the whole assertion passing because the pattern matched nothing —
    # which is how a file-scraping test quietly stops testing anything.
    assert "mcp:grant" in seeded, "the seeding block is no longer where this test looks"
    assert len(seeded) > 20

    unknown = sorted(seeded - PERMISSIONS)
    assert unknown == [], f"migration 0017 seeds undeclared permissions: {unknown}"


# ---- grant shape ----------------------------------------------------------------------


def test_account_scope_refuses_a_scope_id() -> None:
    """`account` plus an id is ambiguous: it would read as account-wide *and* narrowed."""
    with pytest.raises(ValidationError, match="does not take a scope_id"):
        GrantCreate(
            subject_kind=SubjectKind.MEMBER,
            subject_id=uuid.uuid4(),
            role_key="engineer",
            scope_kind=ScopeKind.ACCOUNT,
            scope_id=uuid.uuid4(),
        )


def test_narrow_scope_requires_a_scope_id() -> None:
    """Without one the grant would resolve against nothing and deny everything silently."""
    with pytest.raises(ValidationError, match="requires a scope_id"):
        GrantCreate(
            subject_kind=SubjectKind.MEMBER,
            subject_id=uuid.uuid4(),
            role_key="engineer",
            scope_kind=ScopeKind.PROJECT,
        )


def test_roles_are_granted_to_people_and_teams_only() -> None:
    """An agent gets capability grants, not roles.

    Letting a role be granted to a workload would make the human permission model and the
    machine one the same thing, and they answer different questions.
    """
    with pytest.raises(ValidationError, match="members and teams only"):
        GrantCreate(
            subject_kind=SubjectKind.AGENT,
            subject_id=uuid.uuid4(),
            role_key="engineer",
            scope_kind=ScopeKind.ACCOUNT,
        )


# ---- elevation requests ---------------------------------------------------------------


def test_request_scope_validation_mirrors_grant_validation() -> None:
    """An approver must never be shown a request that cannot be granted."""
    with pytest.raises(ValidationError, match="requires a scope_id"):
        AccessRequestCreate(
            role_key="approver",
            scope_kind=ScopeKind.PROJECT,
            duration_minutes=120,
            reason="Signing off the payments release.",
        )


def test_request_duration_is_bounded_at_both_ends() -> None:
    """A request for a year is a standing privilege with extra steps."""
    with pytest.raises(ValidationError):
        AccessRequestCreate(
            role_key="approver",
            scope_kind=ScopeKind.ACCOUNT,
            duration_minutes=0,
            reason="x",
        )
    with pytest.raises(ValidationError):
        AccessRequestCreate(
            role_key="approver",
            scope_kind=ScopeKind.ACCOUNT,
            duration_minutes=60 * 24 * 365,
            reason="x",
        )


def test_request_requires_a_stated_reason() -> None:
    """The reason is the only thing the approver sees, so an empty one is refused."""
    with pytest.raises(ValidationError):
        AccessRequestCreate(
            role_key="approver",
            scope_kind=ScopeKind.ACCOUNT,
            duration_minutes=60,
            reason="",
        )


def test_risk_rises_with_both_the_role_and_the_duration() -> None:
    """Duration weighs as heavily as the role.

    Long-lived elevation is the pattern that becomes a standing privilege nobody remembers
    granting, so eight hours of `security_admin` and eight hours of `viewer` must not
    classify the same.
    """
    short_elevated = service._risk_of("security_admin", 120)
    long_elevated = service._risk_of("security_admin", 2880)
    short_ordinary = service._risk_of("viewer", 120)

    assert long_elevated == "critical"
    assert short_elevated == "high"
    assert short_ordinary == "low"
