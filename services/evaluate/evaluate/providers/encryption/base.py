"""Encryption provider interface for example payloads."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EncryptionProvider(ABC):
    @abstractmethod
    def encrypt(self, plaintext: bytes) -> bytes: ...

    @abstractmethod
    def decrypt(self, ciphertext: bytes) -> bytes: ...
