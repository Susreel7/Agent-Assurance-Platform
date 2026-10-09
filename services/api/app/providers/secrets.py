"""Secret resolution.

In our cloud secrets arrive as environment variables injected by the platform. In BYOC
they come from whatever the customer already uses, so we must not require a particular
one. Values are cached for the process lifetime — a rotating secret needs a restart,
which is acceptable and is far simpler than a refresh loop nobody will test.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from functools import lru_cache

from app.config import SecretsProvider, Settings, get_settings


class SecretNotFoundError(KeyError):
    pass


class SecretsBackend(ABC):
    @abstractmethod
    def get(self, name: str) -> str: ...

    def get_or_none(self, name: str) -> str | None:
        try:
            return self.get(name)
        except SecretNotFoundError:
            return None


class EnvSecrets(SecretsBackend):
    """Environment variables. Our cloud, development, and air-gapped installs where
    secrets are mounted by the operator."""

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    def get(self, name: str) -> str:
        key = (self._prefix + name).replace("/", "_").replace("-", "_").upper()
        value = os.environ.get(key)
        if value is None:
            raise SecretNotFoundError(key)
        return value


class AwsSecretsManager(SecretsBackend):
    def __init__(self, prefix: str = "", region: str | None = None) -> None:
        import boto3

        self._prefix = prefix
        self._client = boto3.client("secretsmanager", region_name=region)

    @lru_cache(maxsize=64)  # noqa: B019 — process-lifetime cache is intended
    def get(self, name: str) -> str:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.get_secret_value(SecretId=self._prefix + name)
        except ClientError as exc:
            raise SecretNotFoundError(self._prefix + name) from exc
        return str(resp["SecretString"])


class AzureKeyVaultSecrets(SecretsBackend):
    def __init__(self, vault_url: str, prefix: str = "") -> None:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        self._prefix = prefix
        self._client = SecretClient(vault_url, credential=DefaultAzureCredential())

    @lru_cache(maxsize=64)  # noqa: B019
    def get(self, name: str) -> str:
        from azure.core.exceptions import ResourceNotFoundError

        # Key Vault names allow only alphanumerics and hyphens.
        safe = (self._prefix + name).replace("/", "-").replace("_", "-")
        try:
            return self._client.get_secret(safe).value or ""
        except ResourceNotFoundError as exc:
            raise SecretNotFoundError(safe) from exc


class GcpSecretManager(SecretsBackend):
    def __init__(self, project: str, prefix: str = "") -> None:
        from google.cloud import secretmanager

        self._project = project
        self._prefix = prefix
        self._client = secretmanager.SecretManagerServiceClient()

    @lru_cache(maxsize=64)  # noqa: B019
    def get(self, name: str) -> str:
        from google.api_core.exceptions import NotFound

        safe = (self._prefix + name).replace("/", "-").replace("_", "-")
        path = f"projects/{self._project}/secrets/{safe}/versions/latest"
        try:
            return str(self._client.access_secret_version(name=path).payload.data.decode())
        except NotFound as exc:
            raise SecretNotFoundError(path) from exc


class VaultSecrets(SecretsBackend):
    """HashiCorp Vault. Common in banks, which are a target segment, so this backend
    earns its place despite the extra dependency."""

    def __init__(self, addr: str, prefix: str = "", mount: str = "secret") -> None:
        import hvac

        self._prefix = prefix
        self._mount = mount
        self._client = hvac.Client(url=addr)
        if not self._client.is_authenticated():
            # Kubernetes auth is the usual path; the operator configures it.
            raise RuntimeError("Vault client is not authenticated")

    @lru_cache(maxsize=64)  # noqa: B019
    def get(self, name: str) -> str:
        import hvac.exceptions

        try:
            resp = self._client.secrets.kv.v2.read_secret_version(
                path=self._prefix + name, mount_point=self._mount
            )
        except hvac.exceptions.InvalidPath as exc:
            raise SecretNotFoundError(self._prefix + name) from exc

        # Vault KV v2 nests the payload twice. Prefer a conventional `value` key and
        # fall back to the first entry, so a secret written as `{"password": ...}`
        # still resolves rather than failing at startup.
        data = resp["data"]["data"]
        return str(data.get("value") or next(iter(data.values())))


@lru_cache(maxsize=1)
def build_secrets(settings: Settings | None = None) -> SecretsBackend:
    s = settings or get_settings()
    match s.secrets_provider:
        case SecretsProvider.ENV:
            return EnvSecrets(s.secrets_prefix)
        case SecretsProvider.AWS_SECRETS_MANAGER:
            return AwsSecretsManager(s.secrets_prefix, s.cloud_region)
        case SecretsProvider.AZURE_KEY_VAULT:
            url = os.environ.get("AAP_AZURE_VAULT_URL")
            if not url:
                raise ValueError("secrets_provider=az_kv requires AAP_AZURE_VAULT_URL")
            return AzureKeyVaultSecrets(url, s.secrets_prefix)
        case SecretsProvider.GCP_SECRET_MANAGER:
            project = os.environ.get("AAP_GCP_PROJECT")
            if not project:
                raise ValueError("secrets_provider=gcp_sm requires AAP_GCP_PROJECT")
            return GcpSecretManager(project, s.secrets_prefix)
        case SecretsProvider.VAULT:
            addr = os.environ.get("VAULT_ADDR")
            if not addr:
                raise ValueError("secrets_provider=vault requires VAULT_ADDR")
            return VaultSecrets(addr, s.secrets_prefix)
