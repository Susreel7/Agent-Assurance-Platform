from __future__ import annotations

import pytest

from prompt.auth.rbac import assert_may_promote_label
from prompt.errors import AuthorizationError


def test_protected_label_requires_scope() -> None:
    with pytest.raises(AuthorizationError):
        assert_may_promote_label([], "production")


def test_custom_label_no_scope() -> None:
    assert_may_promote_label([], "custom-dev")  # does not raise
