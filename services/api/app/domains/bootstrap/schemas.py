"""The one response the console shell renders from.

Everything here exists because the shell currently assembles the same information from
four or five calls that land in an arbitrary order. That is what produces a half-loaded
screen: navigation renders before permissions arrive, so a link appears and then vanishes,
and a component that fetched identity for itself shows a spinner next to one that has
already finished.

One request, one render. The cost is a slightly larger payload; the benefit is that
"signed in but nothing has loaded yet" stops being a state the UI can be in.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.domains.modules.schemas import ModulesManifestOut


class BootstrapMember(BaseModel):
    """Who you are. Deliberately not the full member record.

    The profile page fetches the rest. What is here is what the shell paints: the avatar,
    the name under it, and the identifiers every later request is attributed to.
    """

    id: UUID
    email: str
    display_name: str
    status: str
    job_title: str | None = None
    avatar_tone: str = "default"
    timezone: str = "UTC"


class BootstrapAccount(BaseModel):
    """Which account, and what shape of install it is."""

    id: UUID
    name: str
    slug: str
    deployment_mode: str
    tenancy: str
    environment: str


class BootstrapAccess(BaseModel):
    """What you may do, flattened, and where.

    ``permissions`` answers "may this person ever"; ``scoped`` answers "may this person
    here". The console uses the first to decide what to render and the second to decide
    what to enable, and both come from the same evaluation so they cannot disagree.
    """

    role_keys: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    scoped: dict[str, list[str]] = Field(default_factory=dict)


class NavItem(BaseModel):
    """One link. The server has already decided you may see it.

    ``icon`` is a name, not a glyph: the client owns the icon set, and shipping SVG in a
    JSON envelope would couple the API to a component library's version.

    ``matches`` exists because several links own more than one route subtree — the
    assurance entry covers five. Active state is computed from ``path`` plus these, by
    matching the URL, never from React state. Deriving it from state is what made one
    click highlight three tabs.
    """

    label: str
    path: str
    icon: str
    end: bool = False
    matches: list[str] = Field(default_factory=list)


class NavGroup(BaseModel):
    label: str | None = None
    items: list[NavItem] = Field(default_factory=list)


class ProductModeOut(StrEnum):
    """Which product the console leads with.

    Not a theme and not a permission. It selects the information architecture: a
    ``ledger`` console puts agent actions first and leaves the accreditation screens
    reachable by URL, an ``assurance`` console does the reverse. Both render the same
    routes from the same `App.tsx`; only the navigation and the home screen differ.
    """

    LEDGER = "ledger"
    ASSURANCE = "assurance"


class BootstrapSession(BaseModel):
    """When this session dies, so the console can renew before it does."""

    id: UUID
    expires_at: datetime
    absolute_expires_at: datetime
    provider_label: str | None = None
    mfa_verified: bool = False


class BootstrapOut(BaseModel):
    member: BootstrapMember
    account: BootstrapAccount
    access: BootstrapAccess
    product_mode: ProductModeOut = ProductModeOut.LEDGER
    """Which information architecture the shell renders. Default ``ledger``."""

    navigation: list[NavGroup] = Field(default_factory=list)
    modules: ModulesManifestOut
    capabilities: dict[str, bool] = Field(default_factory=dict)
    """Named yes/no answers the console would otherwise infer by trying and failing —
    "may I write anything at all", "is this install multi-tenant"."""

    capability_flags: dict[str, bool] = Field(default_factory=dict)
    """Which optional product surfaces this install has turned on.

    Separate from ``capabilities`` because the question is different: ``capabilities``
    is about this caller, ``capability_flags`` is about this install. The accreditation,
    customer, engagement, prompt, evaluate, router, SLA and graph screens are all off
    for a fresh account and stay reachable by URL — a flag removes a link, never a
    route, because a bookmark that stops working is a support ticket."""

    session: BootstrapSession | None = None
    """Absent for a bearer-token caller, which has no console session to describe."""

    generated_at: datetime
    """Freshness. The console shows it when a screen has been open long enough that the
    permissions behind it may have changed."""
