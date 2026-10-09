from __future__ import annotations

import pytest

from prompt.config import Settings
from prompt.errors import EncryptionError
from prompt.providers.encryption.factory import resolve_encryption_provider


def test_aws_kms_requires_optional_extra() -> None:
    settings = Settings()
    provider = resolve_encryption_provider(settings, "kms:aws:alias/test-key")
    with pytest.raises(EncryptionError, match="aap-prompt\\[aws\\]"):
        provider.encrypt(b"hello")
