from __future__ import annotations

import pytest

from observe.auth.internal import verify_internal_token
from observe.config import Settings
from observe.errors import AuthenticationError


def test_internal_token() -> None:
    settings = Settings(internal_service_token="secret")
    verify_internal_token(settings, "Bearer secret")
    with pytest.raises(AuthenticationError):
        verify_internal_token(settings, "Bearer wrong")
