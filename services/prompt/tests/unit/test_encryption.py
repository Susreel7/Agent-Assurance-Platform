from __future__ import annotations

import pytest

from prompt.config import Settings
from prompt.errors import EncryptionError
from prompt.providers.encryption.factory import resolve_encryption_provider


def test_local_fernet_roundtrip(fernet_key: str) -> None:
    settings = Settings(
        encryption_keys_json=f'{{"local:default":"{fernet_key}"}}',
        default_encryption_key_ref="local:default",
    )
    provider = resolve_encryption_provider(settings, "local:default")
    plain = b'{"content":{"messages":[{"role":"user","content":"hi"}]}}'
    cipher = provider.encrypt(plain)
    assert cipher != plain
    assert provider.decrypt(cipher) == plain


def test_kms_ref_explicit(fernet_key: str) -> None:
    settings = Settings(encryption_keys_json=f'{{"local:default":"{fernet_key}"}}')
    kms = resolve_encryption_provider(settings, "kms:aws:alias/example")
    with pytest.raises(EncryptionError, match="aap-prompt\\[aws\\]"):
        kms.encrypt(b"data")
