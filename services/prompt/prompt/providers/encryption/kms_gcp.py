"""GCP Cloud KMS envelope encryption."""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from prompt.errors import EncryptionError
from prompt.providers.encryption.base import EncryptionProvider
from prompt.providers.encryption.envelope import KmsVendor, open_envelope, seal_envelope


def _require_gcp() -> Any:  # noqa: ANN401
    try:
        from google.cloud import kms
    except ImportError as exc:
        raise EncryptionError(
            "kms:gcp refs require optional dependency: pip install 'aap-prompt[gcp]'"
        ) from exc
    return kms


class GcpKmsEnvelopeProvider(EncryptionProvider):
    def __init__(self, key_ref: str, key_resource: str) -> None:
        self._key_ref = key_ref
        self._key_resource = key_resource

    @property
    def key_ref(self) -> str:
        return self._key_ref

    def _client(self) -> Any:  # noqa: ANN401
        kms_mod = _require_gcp()
        return kms_mod.KeyManagementServiceClient()

    def encrypt(self, plaintext: bytes) -> bytes:
        dek = AESGCM.generate_key(bit_length=256)
        client = self._client()
        resp = client.encrypt(request={"name": self._key_resource, "plaintext": dek})
        encrypted_dek = resp.ciphertext
        return seal_envelope(
            vendor=KmsVendor.GCP,
            key_ref=self._key_ref,
            encrypted_dek=encrypted_dek,
            plaintext=plaintext,
            dek=dek,
        )

    def decrypt(self, ciphertext: bytes) -> bytes:
        def decrypt_dek(*, vendor: KmsVendor, key_ref: str, encrypted_dek: bytes) -> bytes:
            if vendor is not KmsVendor.GCP:
                raise EncryptionError("envelope vendor mismatch for gcp provider")
            client = self._client()
            resp = client.decrypt(request={"name": self._key_resource, "ciphertext": encrypted_dek})
            plain = resp.plaintext
            if not isinstance(plain, bytes):
                raise EncryptionError("gcp kms decrypt returned non-bytes plaintext")
            return plain

        return open_envelope(ciphertext, decrypt_dek)
