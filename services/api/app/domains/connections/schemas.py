"""Provider connection boundary models.

No response model in this file can carry secret material. ``credential_ref`` is a pointer
into the customer's own secret provider and ``fingerprint_hex`` is a truncated digest
shown so an operator can confirm a rotation actually changed the key.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domains.registry.schemas import LifecycleState


class ProviderKind(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    BEDROCK = "bedrock"
    VERTEX = "vertex"
    MISTRAL = "mistral"
    COHERE = "cohere"
    VLLM = "vllm"
    OLLAMA = "ollama"
    MCP_HTTP = "mcp_http"
    CUSTOM = "custom"


class AuthKind(StrEnum):
    API_KEY = "api_key"
    OAUTH_CLIENT = "oauth_client"
    IAM_ROLE = "iam_role"
    MTLS = "mtls"
    WORKLOAD_IDENTITY = "workload_identity"
    NONE = "none"


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ROTATING = "rotating"
    DISABLED = "disabled"


class ConnectionCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=256)
    provider_kind: ProviderKind
    auth_kind: AuthKind
    credential_ref: str = Field(min_length=1, max_length=1024)
    owner_team_id: UUID | None = None
    endpoint_url: str | None = Field(default=None, max_length=2048)
    region: str | None = Field(default=None, max_length=64)
    residency_zone: str | None = Field(default=None, max_length=64)
    environments: list[LifecycleState] = Field(min_length=1, max_length=5)
    rotation_due_at: datetime | None = None
    personal: bool = False
    """A developer's own key. Cannot carry production, enforced by check constraint."""

    @model_validator(mode="after")
    def _consistency(self) -> ConnectionCreate:
        if self.auth_kind is AuthKind.NONE and self.credential_ref != "none":
            raise ValueError("auth_kind 'none' requires credential_ref 'none'")
        if self.personal and LifecycleState.PRODUCTION in self.environments:
            raise ValueError("a personal connection cannot be used in production")
        if (
            self.provider_kind
            in (
                ProviderKind.VLLM,
                ProviderKind.OLLAMA,
                ProviderKind.CUSTOM,
                ProviderKind.MCP_HTTP,
            )
            and not self.endpoint_url
        ):
            raise ValueError(f"{self.provider_kind.value} requires an endpoint_url")
        self.environments = list(dict.fromkeys(self.environments))
        return self


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    owner_team_id: UUID | None = None
    endpoint_url: str | None = Field(default=None, max_length=2048)
    region: str | None = Field(default=None, max_length=64)
    residency_zone: str | None = Field(default=None, max_length=64)
    environments: list[LifecycleState] | None = Field(default=None, min_length=1, max_length=5)
    rotation_due_at: datetime | None = None
    status: ConnectionStatus | None = None


class ConnectionRotate(BaseModel):
    """Point the connection at new material.

    Takes a reference, never a value. The gateway resolves the reference through
    ``app/providers``, so this endpoint can be called by somebody who is allowed to
    rotate a key without being allowed to read one.
    """

    credential_ref: str = Field(min_length=1, max_length=1024)
    fingerprint_hex: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    """SHA-256 of the new material, computed by the caller. Proof of change, not the key."""
    rotation_due_at: datetime | None = None
    retire_previous: bool = True


class SecretVersionOut(BaseModel):
    id: UUID
    version_number: int
    credential_ref: str
    fingerprint_prefix: str
    """First 16 hex characters. Enough to compare two versions, not enough to be a key."""
    created_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None
    created_by: str


class ConnectionOut(BaseModel):
    id: UUID
    org_id: UUID
    slug: str
    name: str
    provider_kind: ProviderKind
    auth_kind: AuthKind
    status: ConnectionStatus
    owner_team_id: UUID | None
    personal_member_id: UUID | None
    endpoint_url: str | None
    region: str | None
    residency_zone: str | None
    environments: list[LifecycleState]
    active_secret_version_id: UUID | None
    rotation_due_at: datetime | None
    last_used_at: datetime | None
    last_health_at: datetime | None
    health_detail: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str

    model_config = {"from_attributes": True}


class ConnectionSummary(BaseModel):
    connection: ConnectionOut
    owner_team_name: str | None
    grant_count: int
    active_version: int | None
    rotation_overdue: bool


class ConnectionPage(BaseModel):
    items: list[ConnectionSummary]
    total: int
    limit: int
    offset: int


class ConnectionGrantCreate(BaseModel):
    subject_kind: str = Field(pattern=r"^(agent|team|project)$")
    subject_id: UUID
    environments: list[LifecycleState] = Field(min_length=1, max_length=5)
    reason: str | None = Field(default=None, max_length=1024)
    expires_at: datetime | None = None


class ConnectionGrantOut(BaseModel):
    id: UUID
    connection_id: UUID
    subject_kind: str
    subject_id: UUID
    environments: list[LifecycleState]
    granted_by: str
    reason: str | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResolvedConnection(BaseModel):
    """What the gateway needs to actually make a call, for one subject and environment.

    Returned only to a workload-authenticated caller. It carries the credential
    *reference*, which the gateway exchanges for material through its own secret provider
    — so a leak of this response does not leak a key.
    """

    connection_id: UUID
    provider_kind: ProviderKind
    auth_kind: AuthKind
    credential_ref: str
    endpoint_url: str | None
    region: str | None
    residency_zone: str | None
    version_number: int
