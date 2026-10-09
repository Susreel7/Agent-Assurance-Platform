"""Member, identity and team boundary models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MAX_DIRECTORY_GROUPS = 256

# Matches the CHECK constraint in migration 0017 and nothing more. Deliberately not
# `EmailStr`: a member's email is a display and correlation field, while the thing that
# actually authenticates them is the `(issuer, subject)` pair in `member_identities`.
# Strict RFC validation here would reject addresses the customer's own directory issues
# and the database accepts, which is a support ticket in exchange for no security.
MAX_EMAIL_CHARS = 320


class MemberStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class AvatarTone(StrEnum):
    DEFAULT = "default"
    BLUE = "blue"
    PURPLE = "purple"
    AMBER = "amber"
    DARK = "dark"


class TeamSource(StrEnum):
    MANUAL = "manual"
    DIRECTORY = "directory"


class MemberInvite(BaseModel):
    email: str = Field(min_length=3, max_length=MAX_EMAIL_CHARS)
    display_name: str = Field(min_length=1, max_length=256)
    job_title: str | None = Field(default=None, max_length=256)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    avatar_tone: AvatarTone = AvatarTone.DEFAULT
    primary_team_id: UUID | None = None
    team_ids: list[UUID] = Field(default_factory=list, max_length=64)
    role_keys: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, email: str) -> str:
        """Lowercase and trim, so uniqueness here agrees with the database.

        The unique index is on `lower(email)`. Without normalising at the boundary, two
        invites differing only in case would both look new to this layer and the second
        would fail as an integrity error rather than a clean duplicate.
        """
        email = email.strip().lower()
        if email.find("@") < 1 or email.endswith("@"):
            raise ValueError("email must contain a local part and a domain")
        return email

    @field_validator("team_ids", "role_keys")
    @classmethod
    def _dedupe(cls, values: list) -> list:  # type: ignore[type-arg]
        return list(dict.fromkeys(values))


class MemberUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    job_title: str | None = Field(default=None, max_length=256)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    avatar_tone: AvatarTone | None = None
    primary_team_id: UUID | None = None
    status: MemberStatus | None = None


class MemberOut(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    display_name: str
    status: MemberStatus
    job_title: str | None
    timezone: str
    avatar_tone: AvatarTone
    primary_team_id: UUID | None
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemberSummary(BaseModel):
    """A member plus the derived facts the console list actually renders.

        Team names and role keys are joined in one query rather than fetched per row: a
    thousand-member account otherwise produces a thousand round trips to draw one table.
    """

    member: MemberOut
    team_names: list[str]
    role_keys: list[str]
    identity_count: int
    mfa_verified: bool


class MemberPage(BaseModel):
    items: list[MemberSummary]
    total: int
    limit: int
    offset: int


class IdentityBind(BaseModel):
    """Bind a verified IdP subject to a member.

        ``issuer`` and ``subject`` come from a token this service verified, never from a
    request body field a client chose — the router takes them from the caller's own claims
        when self-binding, and an identity admin supplies them only for directory import.
    """

    issuer: str = Field(min_length=1, max_length=512)
    subject: str = Field(min_length=1, max_length=512)
    email_verified: bool = False
    mfa_verified: bool = False
    directory_groups: list[str] = Field(default_factory=list, max_length=MAX_DIRECTORY_GROUPS)


class IdentityOut(BaseModel):
    id: UUID
    member_id: UUID
    issuer: str
    subject: str
    email_verified: bool
    mfa_verified: bool
    directory_groups: list[str]
    last_login_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    parent_team_id: UUID | None = None
    source: TeamSource = TeamSource.MANUAL
    directory_group_id: str | None = Field(default=None, max_length=256)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    parent_team_id: UUID | None = None


class TeamOut(BaseModel):
    id: UUID
    org_id: UUID
    slug: str
    name: str
    description: str | None
    parent_team_id: UUID | None
    source: TeamSource
    directory_group_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TeamSummary(BaseModel):
    team: TeamOut
    member_count: int
    lead_names: list[str]


class TeamPage(BaseModel):
    items: list[TeamSummary]
    total: int
    limit: int
    offset: int


class TeamMembershipChange(BaseModel):
    member_ids: list[UUID] = Field(min_length=1, max_length=500)
    is_lead: bool = False


class MemberProfile(BaseModel):
    """Everything the signed-in person's own profile page needs, in one response.

    Deliberately not assembled from four endpoints on the client. The profile page is the
    first thing rendered after login, and four sequential requests there is four times
    the latency for no benefit.
    """

    account_name: str
    member: MemberOut
    identities: list[IdentityOut]
    teams: list[TeamOut]
    role_keys: list[str]
    permissions: list[str]
