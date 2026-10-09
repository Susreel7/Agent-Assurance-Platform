"""Encrypt full-capture payload blobs at rest (local provider)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from observe.errors import ObserveError


class PayloadCipher:
    def __init__(self, key_material: str) -> None:
        if not key_material:
            raise ObserveError(
                "OBSERVE_PAYLOAD_ENCRYPTION_KEY is required for full capture mode",
                code="encryption_key_missing",
            )
        self._fernet = Fernet(key_material.encode("utf-8"))

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise ObserveError("payload decrypt failed", code="payload_decrypt_failed") from exc
