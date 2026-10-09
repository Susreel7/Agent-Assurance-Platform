"""Internal RBAC for protected label promotion."""

from __future__ import annotations

from prompt.config import PROTECTED_LABELS
from prompt.errors import AuthorizationError

SCOPE_LABEL_PRODUCTION = "prompt:label:production"
SCOPE_LABEL_STAGING = "prompt:label:staging"
SCOPE_LABEL_LATEST = "prompt:label:latest"

_LABEL_SCOPE: dict[str, str] = {
    "production": SCOPE_LABEL_PRODUCTION,
    "staging": SCOPE_LABEL_STAGING,
    "latest": SCOPE_LABEL_LATEST,
}


def required_scope_for_label(label_name: str) -> str | None:
    normalized = label_name.strip().lower()
    if normalized not in PROTECTED_LABELS:
        return None
    return _LABEL_SCOPE.get(normalized)


def assert_may_promote_label(scopes: list[str], label_name: str) -> None:
    required = required_scope_for_label(label_name)
    if required is None:
        return
    if required not in scopes:
        raise AuthorizationError(f"missing internal scope {required} for label {label_name}")
