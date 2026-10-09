"""The F2 information-architecture invariants that live on the server.

Navigation is a server answer, so the assertions about it belong here rather than in a
browser test. Three of the named invariants in `design/prompts/f2-ui-structure.md` are
properties of this manifest:

``inv_existing_urls_survive``   a capability flag removes a link, never a route
``inv_single_nav_source``       one manifest decides the IA — asserted here by there
                                being exactly two, selected by product mode, and in
                                `services/web/scripts/check-runtime-contract.mjs` by no
                                live layout importing a second nav component

The fourth property is not in the prompt's list but is the bug that produced it: an
active-state rule where one click highlighted three items. A nav item owns a URL subtree,
and two items owning the same subtree is what makes that unrepresentable — so it is
asserted rather than left to the renderer.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from app.config import ProductMode, get_settings
from app.domains.access.schemas import PERMISSIONS, EffectiveAccess
from app.domains.bootstrap.schemas import NavGroup
from app.domains.bootstrap.service import (
    _ASSURANCE_NAVIGATION,
    _LEDGER_NAVIGATION,
    CAPABILITY_FLAGS,
    _Group,
    capability_flags_for,
    navigation_for,
)
from app.domains.modules.schemas import SUITE_MODULE_IDS

ALL_MODULES = frozenset(SUITE_MODULE_IDS)


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _access(*permissions: str, roles: list[str] | None = None) -> EffectiveAccess:
    return EffectiveAccess(
        member_id=uuid.uuid4(),
        role_keys=roles or [],
        permissions=list(permissions),
        scoped={},
    )


def _everything() -> EffectiveAccess:
    """A member who holds every permission, so a missing link is about the IA."""
    return _access(*sorted(PERMISSIONS), roles=["owner"])


def _labels(groups: list[NavGroup]) -> list[str | None]:
    return [group.label for group in groups]


def _paths(groups: list[NavGroup]) -> list[str]:
    return [item.path for group in groups for item in group.items]


def _ledger(**kwargs: object) -> list[NavGroup]:
    flags = kwargs.pop("flags", None) or capability_flags_for(ProductMode.LEDGER)
    assert not kwargs, kwargs
    return navigation_for(_everything(), ALL_MODULES, mode=ProductMode.LEDGER, flags=flags)


# --------------------------------------------------------------------------------------
# The fresh-login story
# --------------------------------------------------------------------------------------


def test_a_fresh_ledger_login_leads_with_the_ledger() -> None:
    """The gate: Home, the ledger, agents and admin — not clients and contracts.

    This is the whole point of the slice. The console shipped an accreditation product to
    someone who installed an action ledger, and the first screen decided which product
    they thought they had bought.
    """
    groups = _ledger()

    assert _labels(groups) == [None, "Ledger", "Agents", "Control", "Admin"]
    assert _paths(groups)[0] == "/"


def test_the_ledger_group_reuses_the_observe_routes() -> None:
    """Named for the customer, routed to the screens that already work.

    Renaming the routes to match the labels would break every `/observe/...` deep link
    written by an earlier session, and would buy a URL nobody reads aloud.
    """
    ledger = next(group for group in _ledger() if group.label == "Ledger")

    assert [(item.label, item.path) for item in ledger.items] == [
        ("Overview", "/observe"),
        ("Actions", "/observe/executions"),
        ("Sessions", "/observe/sessions"),
        ("Live", "/observe/live"),
    ]


def test_the_assurance_product_is_absent_from_a_fresh_ledger_nav() -> None:
    hidden = {"/assurance", "/customers", "/engagements", "/graph", "/sla", "/prompt", "/evaluate"}

    assert hidden.isdisjoint(_paths(_ledger()))


def test_admin_and_mcp_stay_visible_in_ledger_mode() -> None:
    """`/admin/mcp` is explicitly not hideable — V1 needs it and M4 links into it."""
    paths = _paths(_ledger())

    for required in (
        "/admin/mcp",
        "/platform-keys",
        "/admin/connections",
        "/admin/people",
        "/admin/access",
        "/admin/audit",
        "/profile",
        "/agents",
        "/discovery",
    ):
        assert required in paths, required


# --------------------------------------------------------------------------------------
# inv_existing_urls_survive — a flag removes a link, never a route
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flag,path",
    [
        ("accreditation", "/assurance"),
        ("customers", "/customers"),
        ("engagements", "/engagements"),
        ("graph", "/graph"),
        ("sla", "/sla"),
        ("prompt", "/prompt"),
        ("evaluate", "/evaluate"),
        ("router", "/model-routing"),
    ],
)
def test_a_capability_flag_turns_one_link_on(flag: str, path: str) -> None:
    off = capability_flags_for(ProductMode.LEDGER)
    assert path not in _paths(_ledger(flags=off))

    on = {**off, flag: True}
    assert path in _paths(_ledger(flags=on))


def test_every_declared_flag_is_consumed_by_a_nav_entry() -> None:
    """A flag nothing reads is configuration that lies about what it does."""
    consumed = {
        entry.flag
        for manifest in (_LEDGER_NAVIGATION, _ASSURANCE_NAVIGATION)
        for group in manifest
        for entry in group.entries
        if entry.flag is not None
    }

    assert consumed == set(CAPABILITY_FLAGS)


def test_flags_default_off_for_a_fresh_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AAP_ASSURANCE_CAPABILITIES", raising=False)
    get_settings.cache_clear()

    assert capability_flags_for(ProductMode.LEDGER) == dict.fromkeys(CAPABILITY_FLAGS, False)


def test_an_operator_names_the_surfaces_they_want(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AAP_ASSURANCE_CAPABILITIES", "accreditation, sla")
    get_settings.cache_clear()

    flags = capability_flags_for(ProductMode.LEDGER)

    assert flags["accreditation"] is True
    assert flags["sla"] is True
    assert flags["graph"] is False


def test_assurance_mode_restores_the_whole_product() -> None:
    flags = capability_flags_for(ProductMode.ASSURANCE)
    groups = navigation_for(_everything(), ALL_MODULES, mode=ProductMode.ASSURANCE, flags=flags)

    assert all(flags.values())
    assert _labels(groups) == [None, "Agents", "Activity", "Control", "Assurance", "Admin"]
    assert "/observe/traces" in _paths(groups)


# --------------------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------------------


def test_a_permission_the_member_lacks_removes_the_link() -> None:
    groups = navigation_for(
        _access(),
        ALL_MODULES,
        mode=ProductMode.LEDGER,
        flags=capability_flags_for(ProductMode.ASSURANCE),
    )

    # Home and Profile need no permission; nothing else survives.
    assert _paths(groups) == ["/", "/profile"]


def test_an_unlicensed_module_removes_the_link() -> None:
    groups = navigation_for(
        _everything(),
        frozenset(),
        mode=ProductMode.LEDGER,
        flags=capability_flags_for(ProductMode.ASSURANCE),
    )

    assert not [path for path in _paths(groups) if path.startswith("/observe")]


def test_an_emptied_group_disappears_rather_than_rendering_a_heading() -> None:
    """A visible "Control" with nothing under it tells somebody there is a section they
    cannot see, which is both useless to them and more than they need to know."""
    groups = navigation_for(
        _access("agent:read"),
        ALL_MODULES,
        mode=ProductMode.LEDGER,
        flags=capability_flags_for(ProductMode.LEDGER),
    )

    assert all(group.items for group in groups)
    assert "Control" not in _labels(groups)


# --------------------------------------------------------------------------------------
# One click, one highlight
# --------------------------------------------------------------------------------------


def _owned_prefixes(manifest: tuple[_Group, ...]) -> Iterator[tuple[str, str]]:
    for group in manifest:
        for entry in group.entries:
            item = entry.item
            label = f"{group.label or 'root'} · {item.label}"
            if item.end:
                continue
            for prefix in (item.path, *item.matches):
                yield label, prefix


@pytest.mark.parametrize("manifest", [_LEDGER_NAVIGATION, _ASSURANCE_NAVIGATION])
def test_no_two_items_claim_the_same_url_subtree(manifest: tuple[_Group, ...]) -> None:
    """The reported bug was one click highlighting three tabs.

    `Shell.tsx` computes active state by prefix match, so two items claiming overlapping
    prefixes light up together no matter how the renderer is written. `end=True` opts an
    item out of prefix matching and is how `/observe` and `/observe/executions` coexist.
    """
    claims = list(_owned_prefixes(manifest))

    for label, prefix in claims:
        for other_label, other_prefix in claims:
            if label == other_label:
                continue
            assert not (prefix == other_prefix or prefix.startswith(f"{other_prefix}/")), (
                f"{label} ({prefix}) is inside {other_label} ({other_prefix}); both will highlight"
            )


@pytest.mark.parametrize("manifest", [_LEDGER_NAVIGATION, _ASSURANCE_NAVIGATION])
def test_every_path_appears_once(manifest: tuple[_Group, ...]) -> None:
    paths = [entry.item.path for group in manifest for entry in group.entries]

    assert len(paths) == len(set(paths)), sorted(paths)


@pytest.mark.parametrize("manifest", [_LEDGER_NAVIGATION, _ASSURANCE_NAVIGATION])
def test_every_declared_permission_exists(manifest: tuple[_Group, ...]) -> None:
    """A link gated on a permission nothing can grant is a link nobody ever sees.

    The vocabulary is closed and mirrored in the `roles` check constraint, so a typo here
    would be invisible until someone asked why the MCP registry had vanished.
    """
    for group in manifest:
        for entry in group.entries:
            if entry.permission is not None:
                assert entry.permission in PERMISSIONS, entry.permission
            if entry.module is not None:
                assert entry.module in SUITE_MODULE_IDS, entry.module
