"""Customer key abstraction for artifact bodies at rest."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EncryptionProvider(ABC):
    @abstractmethod
    def encrypt(self, plaintext: bytes) -> bytes: ...

    @abstractmethod
    def decrypt(self, ciphertext: bytes) -> bytes: ...

    @property
    @abstractmethod
    def key_ref(self) -> str: ...

    @property
    def is_local(self) -> bool:
        return self.key_ref.startswith("local:")


def is_kms_key_ref(key_ref: str) -> bool:
    return key_ref.startswith("kms:")
