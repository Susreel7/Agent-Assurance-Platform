"""Access-control boundary models.

Permissions are ``resource:action`` strings. The closed set lives here and in the
``roles`` check constraint, so a typo in a custom role is rejected at both ends rather
than creating a permission nothing will ever check.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# The vocabulary. Grouped by resource for readability; the flat frozenset below is what
# validation uses.
PERMISSIONS: frozenset[str] = frozenset(
    {
        # People and structure
        "member:read",
        "member:write",
        "team:read",
        "team:write",
        "project:read",
        "project:write",
        # Agents and their runtime
        "agent:read",
        "agent:write",
        "agent:run",
        "agent:publish",
        "activity:read",
        "activity:replay",
        "registry:read",
        "registry:write",
        "prompt:write",
        "evaluate:write",
        # Credentials and connections
        "connection:read",
        "connection:write",
        "connection:rotate",
        "key:read",
        "key:write",
        "key:revoke",
        # Tool surface. `discover` records what a server advertises, `approve` accepts that
        # capability set as reviewed, and `grant` hands it to a subject. Three permissions
        # because they are three different powers: someone who may refresh an inventory is
        # not thereby someone who may decide a destructive tool is safe, and someone who
        # decides that is not thereby someone who may point production agents at it.
        "mcp:read",
        "mcp:write",
        "mcp:discover",
        "mcp:invoke",
        "mcp:approve",
        "mcp:grant",
        "mcp:quarantine",
        # Governance
        "assurance:read",
        "evidence:read",
        "policy:write",
        "release:approve",
        "accreditation:approve",
        "materiality:adjudicate",
        # Access control itself
        "access:read",
        "access:write",
        "access:approve",
        # The one permission that reveals captured content
        "payload:reveal",
        # Audit
        "audit:read",
    }
)

MAX_ROLE_PERMISSIONS = 256
MIN_REQUEST_MINUTES = 15
MAX_REQUEST_MINUTES = 43200  # 30 days


class SubjectKind(StrEnum):
    MEMBER = "member"
    TEAM = "team"
    AGENT = "agent"
    AGENT_VERSION = "agent_version"
    WORKLOAD = "workload"
    PROJECT = "project"


class ScopeKind(StrEnum):
    ACCOUNT = "account"
    PROJECT = "project"
    ENVIRONMENT = "environment"
    AGENT = "agent"
    MCP_SERVER = "mcp_server"
    ENGAGEMENT = "engagement"


class RequestState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RoleOut(BaseModel):
    id: UUID
    org_id: UUID | None
    key: str
    name: str
    description: str
    builtin: bool
    permissions: list[str]
    assignable_scopes: list[ScopeKind]
    separation_of_duty: bool

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    """A tenant-defined role. Built-in roles are seeded by migration and immutable."""

    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)
    permissions: list[str] = Field(min_length=1, max_length=MAX_ROLE_PERMISSIONS)
    assignable_scopes: list[ScopeKind] = Field(min_length=1, max_length=6)
    separation_of_duty: bool = False

    @field_validator("permissions")
    @classmethod
    def _known_permissions(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - PERMISSIONS)
        if unknown:
            raise ValueError(f"unknown permissions: {', '.join(unknown)}")
        return sorted(set(values))


class GrantCreate(BaseModel):
    subject_kind: SubjectKind
    subject_id: UUID
    role_key: str = Field(min_length=1, max_length=64)
    scope_kind: ScopeKind
    scope_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=1024)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _scope_id_matches_kind(self) -> GrantCreate:
        if self.scope_kind is ScopeKind.ACCOUNT and self.scope_id is not None:
            raise ValueError("account scope does not take a scope_id")
        if self.scope_kind is not ScopeKind.ACCOUNT and self.scope_id is None:
            raise ValueError(f"{self.scope_kind.value} scope requires a scope_id")
        if self.subject_kind not in (SubjectKind.MEMBER, SubjectKind.TEAM):
            raise ValueError("role grants apply to members and teams only")
        return self


class GrantOut(BaseModel):
    id: UUID
    org_id: UUID
    subject_kind: SubjectKind
    subject_id: UUID
    role_key: str
    scope_kind: ScopeKind
    scope_id: UUID | None
    granted_by: str
    reason: str | None
    request_id: UUID | None
    expires_at: datetime | None
    revoked_at: datetime | None
    revoked_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GrantSummary(BaseModel):
    """A grant with the display labels the console needs, resolved server-side."""

    grant: GrantOut
    subject_label: str
    role_name: str
    permissions: list[str]
    scope_label: str


class GrantPage(BaseModel):
    items: list[GrantSummary]
    total: int
    limit: int
    offset: int


class AccessRequestCreate(BaseModel):
    role_key: str = Field(min_length=1, max_length=64)
    scope_kind: ScopeKind
    scope_id: UUID | None = None
    duration_minutes: int = Field(ge=MIN_REQUEST_MINUTES, le=MAX_REQUEST_MINUTES)
    reason: str = Field(min_length=1, max_length=1024)
    ticket_ref: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _scope_id_matches_kind(self) -> AccessRequestCreate:
        if self.scope_kind is ScopeKind.ACCOUNT and self.scope_id is not None:
            raise ValueError("account scope does not take a scope_id")
        if self.scope_kind is not ScopeKind.ACCOUNT and self.scope_id is None:
            raise ValueError(f"{self.scope_kind.value} scope requires a scope_id")
        return self


class AccessRequestDecision(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1024)
    # An approver may shorten a request but never lengthen it. Enforced in the service,
    # because the ceiling is the requested duration and this model cannot see it.
    granted_minutes: int | None = Field(default=None, ge=MIN_REQUEST_MINUTES)


class AccessRequestOut(BaseModel):
    id: UUID
    org_id: UUID
    requester_member_id: UUID
    role_key: str
    scope_kind: ScopeKind
    scope_id: UUID | None
    duration_minutes: int
    reason: str
    ticket_ref: str | None
    risk: RiskTier
    state: RequestState
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    granted_grant_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccessRequestPage(BaseModel):
    items: list[AccessRequestOut]
    total: int
    limit: int
    offset: int


class EffectiveAccess(BaseModel):
    """What one member may actually do, flattened.

        ``permissions`` is the union across every live grant. ``scoped`` answers the narrower
    question the enforcement path asks: this permission, on this resource.
    """

    member_id: UUID
    role_keys: list[str]
    permissions: list[str]
    scoped: dict[str, list[str]] = Field(default_factory=dict)
    """Permission -> the scope keys it holds at, as ``"kind:id"`` or ``"account"``."""

    def allows(self, permission: str, scope_key: str = "account") -> bool:
        """True when this permission is held at ``scope_key`` or at account level.

        Account scope subsumes narrower scopes deliberately: a security admin granted at
        account level should not need a per-project grant to answer a page-out.
        """
        held = self.scoped.get(permission)
        if held is None:
            return False
        return "account" in held or scope_key in held
