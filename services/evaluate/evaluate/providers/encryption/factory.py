"""Resolve encryption providers by key reference."""

from __future__ import annotations

from evaluate.config import Settings
from evaluate.errors import EncryptionError
from evaluate.providers.encryption.base import EncryptionProvider
from evaluate.providers.encryption.fernet_local import FernetLocalProvider


def get_encryption_provider(settings: Settings, key_ref: str) -> EncryptionProvider:
    keys = settings.encryption_key_map()
    material = keys.get(key_ref)
    if not material:
        raise EncryptionError(f"unknown encryption key ref: {key_ref}")
    if key_ref.startswith("local:"):
        return FernetLocalProvider(material)
    return FernetLocalProvider(material)
