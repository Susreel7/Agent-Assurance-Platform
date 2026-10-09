"""AWS KMS envelope encryption."""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from prompt.errors import EncryptionError
from prompt.providers.encryption.base import EncryptionProvider
from prompt.providers.encryption.envelope import KmsVendor, open_envelope, seal_envelope


def _require_boto3() -> Any:  # noqa: ANN401
    try:
        import boto3
    except ImportError as exc:
        raise EncryptionError(
            "kms:aws refs require optional dependency: pip install 'aap-prompt[aws]'"
        ) from exc
    return boto3


class AwsKmsEnvelopeProvider(EncryptionProvider):
    def __init__(self, key_ref: str, key_id: str) -> None:
        self._key_ref = key_ref
        self._key_id = key_id

    @property
    def key_ref(self) -> str:
        return self._key_ref

    def encrypt(self, plaintext: bytes) -> bytes:
        boto3 = _require_boto3()
        client = boto3.client("kms")
        dek = AESGCM.generate_key(bit_length=256)
        resp = client.encrypt(KeyId=self._key_id, Plaintext=dek)
        encrypted_dek = resp["CiphertextBlob"]
        return seal_envelope(
            vendor=KmsVendor.AWS,
            key_ref=self._key_ref,
            encrypted_dek=encrypted_dek,
            plaintext=plaintext,
            dek=dek,
        )

    def decrypt(self, ciphertext: bytes) -> bytes:
        boto3 = _require_boto3()
        client = boto3.client("kms")

        def decrypt_dek(*, vendor: KmsVendor, key_ref: str, encrypted_dek: bytes) -> bytes:
            if vendor is not KmsVendor.AWS:
                raise EncryptionError("envelope vendor mismatch for aws provider")
            resp = client.decrypt(CiphertextBlob=encrypted_dek)
            plain = resp["Plaintext"]
            if not isinstance(plain, bytes):
                raise EncryptionError("aws kms decrypt returned non-bytes plaintext")
            return plain

        return open_envelope(ciphertext, decrypt_dek)
