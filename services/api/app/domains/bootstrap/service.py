"""Assemble the shell's one response, and decide the navigation it renders.

The navigation manifest lives here rather than in the client for one reason: the client
cannot be trusted to decide what it may see. A hidden link is a UI nicety, but a link the
server would refuse is a dead end the user has no way to understand — they clicked
something the product offered them and got a red box.

So each entry declares the permission and the licensed module it needs, and this module
filters. What ships to the browser is a list of things that will work.

There are two manifests because there are two products stacked in one console. A fresh
install is a ledger install and leads with agent actions; the accreditation-era estate is
what earlier customers bought and still works. Selecting between them here, once, is what
stops the alternative — the same conditional repeated across `App.tsx`, `Shell.tsx`, the
home screen and three feature layouts, which is how the two navigations came to disagree
about which product was primary in the first place.

An assurance route that is not in the ledger manifest is still routable. Hiding a link is
a statement about what this install leads with; refusing the URL would be a statement that
the screen no longer exists, and it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError, Reason
from app.config import ProductMode, get_settings
from app.domains.access import service as access_service
from app.domains.access.schemas import EffectiveAccess
from app.domains.auth.service import ActiveSession
from app.domains.bootstrap import repository as repo
from app.domains.bootstrap.schemas import (
    BootstrapAccess,
    BootstrapAccount,
    BootstrapMember,
    BootstrapOut,
    BootstrapSession,
    NavGroup,
    NavItem,
    ProductModeOut,
)
from app.domains.members import service as members_service
from app.domains.modules import service as modules_service
from app.domains.modules.schemas import SUITE_MODULE_IDS


@dataclass(frozen=True, slots=True)
class _Entry:
    """A navigation item plus the conditions under which it is shown.

    ``permission`` is the platform permission the destination's own guard will demand.
    ``module`` is the licensed suite module it belongs to. ``flag`` is the optional
    product surface it belongs to, which is a property of the install rather than of the
    caller. All three are checked here, so a link and the endpoint behind it cannot
    disagree about who may use them.

    A ``flag`` hides a link. It never hides a route: `App.tsx` keeps serving every URL,
    because a bookmark that stops working reads as a broken product, and the assurance
    screens are still the product somebody bought.
    """

    item: NavItem
    permission: str | None = None
    module: str | None = None
    flag: str | None = None


@dataclass(frozen=True, slots=True)
class _Group:
    label: str | None
    entries: tuple[_Entry, ...]


def _item(label: str, path: str, icon: str, **kwargs: object) -> NavItem:
    return NavItem(label=label, path=path, icon=icon, **kwargs)  # type: ignore[arg-type]


# The optional surfaces. Every one of these is off for a fresh account and on only when
# the install names it in `AAP_ASSURANCE_CAPABILITIES` — except in assurance mode, where
# they are what the customer bought and are all on.
#
# These are the accreditation-era product and the runtime suite. Both still work; neither
# is what a new install is for, and putting eleven of them in the sidebar on first login
# is why the console read as somebody else's product.
CAPABILITY_FLAGS: tuple[str, ...] = (
    "accreditation",
    "customers",
    "engagements",
    "graph",
    "sla",
    "prompt",
    "evaluate",
    "router",
)


# Shared by both modes. The ledger lives at the Observe routes because Observe is already
# the execution plane: reusing it is the difference between a screen and a rewrite. The
# labels differ from the route names on purpose — a customer reads "Actions", the code
# reads `/observe/executions`, and renaming the routes would break every deep link in
# every earlier session for no gain.
_LEDGER_NAVIGATION: tuple[_Group, ...] = (
    _Group(None, (_Entry(_item("Home", "/", "home", end=True)),)),
    _Group(
        "Ledger",
        (
            _Entry(
                _item("Overview", "/observe", "activity", end=True),
                permission="activity:read",
                module="observe",
            ),
            _Entry(
                _item("Actions", "/observe/executions", "rows"),
                permission="activity:read",
                module="observe",
            ),
            _Entry(
                _item("Sessions", "/observe/sessions", "network"),
                permission="activity:read",
                module="observe",
            ),
            _Entry(
                _item("Live", "/observe/live", "activity", end=True),
                permission="activity:read",
                module="observe",
            ),
        ),
    ),
    _Group(
        "Agents",
        (
            _Entry(_item("Inventory", "/agents", "cpu"), permission="agent:read"),
            _Entry(_item("Discovery", "/discovery", "search", end=True), permission="agent:read"),
        ),
    ),
    _Group(
        "Control",
        (
            _Entry(_item("MCP", "/admin/mcp", "network"), permission="mcp:read"),
            _Entry(_item("Platform Keys", "/platform-keys", "key"), permission="key:read"),
            _Entry(
                _item("Connections", "/admin/connections", "plug"),
                permission="connection:read",
            ),
            _Entry(
                _item("Models & routing", "/model-routing", "layers", matches=["/router"]),
                permission="registry:read",
                module="router",
                flag="router",
            ),
        ),
    ),
    _Group(
        "Assurance",
        (
            _Entry(
                _item(
                    "Assurance center",
                    "/assurance",
                    "shield",
                    matches=["/releases", "/findings", "/evidence", "/accreditations"],
                ),
                permission="assurance:read",
                flag="accreditation",
            ),
            # `assurance:read` rather than a permission per screen. Four new permission
            # strings would mean a migration to the `roles` check constraint, and they
            # would all be granted together anyway: these are one product, and it is the
            # one `assurance:read` already names.
            _Entry(
                _item("Clients", "/customers", "users"),
                permission="assurance:read",
                flag="customers",
            ),
            _Entry(
                _item("Engagements", "/engagements", "layers"),
                permission="assurance:read",
                flag="engagements",
            ),
            _Entry(
                _item("Graph", "/graph", "waypoints"), permission="assurance:read", flag="graph"
            ),
            _Entry(
                _item("Service levels", "/sla", "sliders"),
                permission="assurance:read",
                flag="sla",
            ),
            _Entry(
                _item("Prompt", "/prompt", "layers"),
                permission="prompt:write",
                module="prompt",
                flag="prompt",
            ),
            _Entry(
                _item("Evaluate", "/evaluate", "shield", end=True),
                permission="evaluate:write",
                module="evaluate",
                flag="evaluate",
            ),
        ),
    ),
    _Group(
        "Admin",
        (
            _Entry(_item("People", "/admin/people", "users"), permission="member:read"),
            _Entry(_item("Access", "/admin/access", "lock"), permission="access:read"),
            _Entry(_item("Audit", "/admin/audit", "activity"), permission="audit:read"),
            _Entry(_item("Profile", "/profile", "user", end=True)),
        ),
    ),
)


# The accreditation-era architecture, kept whole for the installs that bought it. This is
# what `Shell.tsx` rendered before F2, moved here unchanged apart from the flags, so that
# switching `AAP_PRODUCT_MODE` is a real switch and not a partial one.
_ASSURANCE_NAVIGATION: tuple[_Group, ...] = (
    _Group(None, (_Entry(_item("Home", "/", "home", end=True)),)),
    _Group(
        "Agents",
        (_Entry(_item("Inventory", "/agents", "cpu"), permission="agent:read"),),
    ),
    _Group(
        "Activity",
        (
            _Entry(
                _item("Overview", "/observe", "activity", end=True),
                permission="activity:read",
                module="observe",
            ),
            _Entry(
                _item("Executions", "/observe/executions", "network"),
                permission="activity:read",
                module="observe",
            ),
            _Entry(
                _item("Sessions", "/observe/sessions", "rows"),
                permission="activity:read",
                module="observe",
            ),
            _Entry(
                _item("Traces", "/observe/traces", "waypoints"),
                permission="activity:read",
                module="observe",
            ),
            _Entry(
                _item("People activity", "/observe/analytics", "users", end=True),
                permission="activity:read",
                module="observe",
            ),
            _Entry(
                _item("Live activity", "/observe/live", "activity", end=True),
                permission="activity:read",
                module="observe",
            ),
        ),
    ),
    _Group(
        "Control",
        (
            _Entry(_item("Control center", "/control", "sliders"), permission="registry:read"),
            _Entry(
                _item("Models & routing", "/model-routing", "layers", matches=["/router"]),
                permission="registry:read",
                module="router",
            ),
            _Entry(_item("MCP registry", "/admin/mcp", "network"), permission="mcp:read"),
            _Entry(
                _item("Connections", "/admin/connections", "plug"),
                permission="connection:read",
            ),
            _Entry(_item("Platform Keys", "/platform-keys", "key"), permission="key:read"),
        ),
    ),
    _Group(
        "Assurance",
        (
            _Entry(
                _item(
                    "Assurance center",
                    "/assurance",
                    "shield",
                    matches=["/releases", "/findings", "/evidence", "/evaluate", "/accreditations"],
                ),
                permission="assurance:read",
            ),
        ),
    ),
    _Group(
        "Admin",
        (
            _Entry(_item("People & teams", "/admin/people", "users"), permission="member:read"),
            _Entry(_item("Roles & access", "/admin/access", "lock"), permission="access:read"),
            _Entry(_item("Security audit", "/admin/audit", "activity"), permission="audit:read"),
        ),
    ),
)


def capability_flags_for(mode: ProductMode) -> dict[str, bool]:
    """Which optional surfaces this install has turned on.

    Assurance mode turns all of them on, because in that mode they are the product. A
    ledger install starts with none and the operator names the ones they want.
    """
    if mode is ProductMode.ASSURANCE:
        return dict.fromkeys(CAPABILITY_FLAGS, True)
    named = {name.strip() for name in get_settings().assurance_capabilities}
    return {name: name in named for name in CAPABILITY_FLAGS}


def navigation_for(
    access: EffectiveAccess,
    entitled: frozenset[str],
    *,
    mode: ProductMode,
    flags: dict[str, bool],
) -> list[NavGroup]:
    """Filter the manifest to what this member may actually open.

    A group whose every item is filtered out disappears with it. Rendering an empty
    "Control" heading tells somebody there is a section they cannot see, which is both
    useless to them and more than they need to know.
    """
    manifest = _ASSURANCE_NAVIGATION if mode is ProductMode.ASSURANCE else _LEDGER_NAVIGATION
    groups: list[NavGroup] = []
    for group in manifest:
        items = [
            entry.item
            for entry in group.entries
            if (entry.permission is None or entry.permission in access.permissions)
            and (entry.module is None or entry.module in entitled)
            and (entry.flag is None or flags.get(entry.flag, False))
        ]
        if items:
            groups.append(NavGroup(label=group.label, items=items))
    return groups


async def bootstrap(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    *,
    console: ActiveSession | None,
    read_only: bool,
) -> BootstrapOut:
    """Identity, permissions, navigation and licence state, in one round trip.

    ``read_only`` is passed in rather than read here because the licence verdict is
    request-pipeline state held by `app/api/deps`, and a domain service reaching back into
    the API layer to fetch it would invert the dependency this file is on the right side
    of.
    """
    member = await members_service.member_by_id(session, org_id, member_id)
    if member is None:
        raise ApiError(
            Reason.NOT_PROVISIONED,
            message="You are signed in, but you are not a member of this account.",
        )

    account = await _account(session, org_id)
    access = await access_service.effective_access(session, org_id, member_id)
    manifest = modules_service.build_effective_manifest()
    entitled = frozenset(
        module_id
        for module_id in SUITE_MODULE_IDS
        if manifest.modules[module_id].enabled and manifest.modules[module_id].access.read
    )
    settings = get_settings()
    mode = settings.product_mode
    flags = capability_flags_for(mode)

    return BootstrapOut(
        member=BootstrapMember(
            id=member.id,
            email=member.email,
            display_name=member.display_name,
            status=member.status,
            job_title=member.job_title,
            avatar_tone=member.avatar_tone,
            timezone=member.timezone,
        ),
        account=account,
        access=BootstrapAccess(
            role_keys=access.role_keys,
            permissions=access.permissions,
            scoped=access.scoped,
        ),
        product_mode=ProductModeOut(mode.value),
        navigation=navigation_for(access, entitled, mode=mode, flags=flags),
        modules=manifest,
        capabilities={
            "multi_tenant": not settings.is_single_tenant,
            "can_write": bool(access.permissions) and not read_only,
            "development": settings.environment == "development",
        },
        capability_flags=flags,
        session=_session_out(console),
        generated_at=datetime.now(tz=UTC),
    )


def _session_out(console: ActiveSession | None) -> BootstrapSession | None:
    if console is None:
        return None
    return BootstrapSession(
        id=console.id,
        expires_at=console.expires_at,
        absolute_expires_at=console.absolute_expires_at,
        mfa_verified=console.mfa_verified,
    )


async def _account(session: AsyncSession, org_id: UUID) -> BootstrapAccount:
    row = await repo.account(session, org_id)
    if row is None:
        raise ApiError(Reason.NOT_PROVISIONED, message="That account no longer exists.")
    settings = get_settings()
    return BootstrapAccount(
        id=row.id,
        name=row.name,
        slug=row.slug,
        deployment_mode=str(settings.deployment_mode),
        tenancy=str(settings.tenancy),
        environment=settings.environment,
    )
