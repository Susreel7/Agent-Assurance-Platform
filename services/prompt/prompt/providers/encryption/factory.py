"""Resolve encryption providers from explicit key references."""

from __future__ import annotations

from prompt.config import Settings
from prompt.errors import EncryptionError
from prompt.providers.encryption.base import EncryptionProvider, is_kms_key_ref
from prompt.providers.encryption.fernet_local import LocalFernetProvider
from prompt.providers.encryption.kms_aws import AwsKmsEnvelopeProvider
from prompt.providers.encryption.kms_azure import AzureKeyVaultEnvelopeProvider
from prompt.providers.encryption.kms_gcp import GcpKmsEnvelopeProvider


def _parse_kms_ref(key_ref: str) -> EncryptionProvider:
    if not is_kms_key_ref(key_ref):
        raise EncryptionError(f"invalid kms key ref: {key_ref}")
    if not key_ref.startswith("kms:"):
        raise EncryptionError(f"malformed kms key ref: {key_ref}")
    rest = key_ref.removeprefix("kms:")
    cloud, sep, target = rest.partition(":")
    if not sep or not target:
        raise EncryptionError(f"malformed kms key ref: {key_ref}")
    cloud = cloud.lower()
    if cloud == "aws":
        return AwsKmsEnvelopeProvider(key_ref, target)
    if cloud == "azure":
        if "#" not in target:
            raise EncryptionError("kms:azure ref must be vault_url#key_name")
        vault_url, key_name = target.split("#", 1)
        return AzureKeyVaultEnvelopeProvider(key_ref, vault_url, key_name)
    if cloud == "gcp":
        return GcpKmsEnvelopeProvider(key_ref, target)
    raise EncryptionError(f"unsupported kms cloud in ref: {key_ref}")


def resolve_encryption_provider(settings: Settings, key_ref: str) -> EncryptionProvider:
    if is_kms_key_ref(key_ref):
        return _parse_kms_ref(key_ref)
    if not key_ref.startswith("local:"):
        raise EncryptionError(f"unsupported encryption key ref prefix: {key_ref}")
    key_map = settings.encryption_key_map()
    material = key_map.get(key_ref)
    if material is None:
        raise EncryptionError(f"no Fernet material configured for key ref {key_ref}")
    return LocalFernetProvider(key_ref, material)


def default_encryption_provider(settings: Settings) -> EncryptionProvider:
    return resolve_encryption_provider(settings, settings.default_encryption_key_ref)
