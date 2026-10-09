"""Local Fernet encryption for BYOC dev and airgap deployments."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from prompt.errors import EncryptionError
from prompt.providers.encryption.base import EncryptionProvider


class LocalFernetProvider(EncryptionProvider):
    def __init__(self, key_ref: str, fernet_key: str) -> None:
        if not key_ref.startswith("local:"):
            msg = "LocalFernetProvider requires local: key_ref"
            raise ValueError(msg)
        try:
            self._fernet = Fernet(fernet_key.encode("ascii"))
        except Exception as exc:  # noqa: BLE001
            raise EncryptionError("invalid Fernet key material") from exc
        self._key_ref = key_ref

    @property
    def key_ref(self) -> str:
        return self._key_ref

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise EncryptionError("decryption failed") from exc
