"""Local Fernet encryption for development and airgap."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from evaluate.errors import EncryptionError
from evaluate.providers.encryption.base import EncryptionProvider


class FernetLocalProvider(EncryptionProvider):
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("ascii") if isinstance(key, str) else key)

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise EncryptionError("decryption failed") from exc
