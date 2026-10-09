"""Azure Key Vault envelope encryption."""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from prompt.errors import EncryptionError
from prompt.providers.encryption.base import EncryptionProvider
from prompt.providers.encryption.envelope import KmsVendor, open_envelope, seal_envelope


def _require_azure() -> tuple[Any, Any, Any, Any]:
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.keys import KeyClient
        from azure.keyvault.keys.crypto import CryptographyClient, EncryptionAlgorithm
    except ImportError as exc:
        raise EncryptionError(
            "kms:azure refs require optional dependency: pip install 'aap-prompt[azure]'"
        ) from exc
    return DefaultAzureCredential, KeyClient, CryptographyClient, EncryptionAlgorithm


class AzureKeyVaultEnvelopeProvider(EncryptionProvider):
    def __init__(self, key_ref: str, vault_url: str, key_name: str) -> None:
        self._key_ref = key_ref
        self._vault_url = vault_url
        self._key_name = key_name

    @property
    def key_ref(self) -> str:
        return self._key_ref

    def _crypto_client(self) -> Any:  # noqa: ANN401
        dac, key_client, crypto_client, _ = _require_azure()
        credential = dac()
        key = key_client(vault_url=self._vault_url, credential=credential).get_key(self._key_name)
        return crypto_client(key, credential=credential)

    def encrypt(self, plaintext: bytes) -> bytes:
        _, _, _, enc_alg = _require_azure()
        dek = AESGCM.generate_key(bit_length=256)
        crypto = self._crypto_client()
        result = crypto.encrypt(enc_alg.rsa_oaep_256, dek)
        encrypted_dek = result.ciphertext
        return seal_envelope(
            vendor=KmsVendor.AZURE,
            key_ref=self._key_ref,
            encrypted_dek=encrypted_dek,
            plaintext=plaintext,
            dek=dek,
        )

    def decrypt(self, ciphertext: bytes) -> bytes:
        _, _, _, enc_alg = _require_azure()

        def decrypt_dek(*, vendor: KmsVendor, key_ref: str, encrypted_dek: bytes) -> bytes:
            if vendor is not KmsVendor.AZURE:
                raise EncryptionError("envelope vendor mismatch for azure provider")
            crypto = self._crypto_client()
            result = crypto.decrypt(enc_alg.rsa_oaep_256, encrypted_dek)
            plain = result.plaintext
            if not isinstance(plain, bytes):
                raise EncryptionError("azure key vault decrypt returned non-bytes plaintext")
            return plain

        return open_envelope(ciphertext, decrypt_dek)
