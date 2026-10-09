"""Lazy import of the API release differ and gate logic.

The control-plane package is optional so CI images that only call the platform API stay
lightweight. ``aap diff`` and ``aap preview --offline`` need the same code the API runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

_OFFLINE_INSTALL_HINT = (
    "Install the offline extra: pip install 'aap-cli[offline]' "
    "(requires the aap-api package from this repository)."
)


class OfflineDependencyError(RuntimeError):
    pass


if TYPE_CHECKING:
    from app.domains.releases.schemas import ReleaseDiff, ReleaseGateVerdict


def diff_descriptors(before: dict[str, Any] | None, after: dict[str, Any]) -> ReleaseDiff:
    try:
        from app.domains.releases.differ import diff_descriptors as _diff
    except ImportError as exc:
        raise OfflineDependencyError(_OFFLINE_INSTALL_HINT) from exc
    return _diff(before, after)


def preview_offline(before: dict[str, Any] | None, after: dict[str, Any]) -> ReleaseGateVerdict:
    try:
        from app.domains.releases.service import preview_release
    except ImportError as exc:
        raise OfflineDependencyError(_OFFLINE_INSTALL_HINT) from exc
    return preview_release(before, after)
