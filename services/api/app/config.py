"""Single source of configuration truth.

Nothing else in the codebase reads ``os.environ``. Every deployment difference between our
cloud, a customer's cloud (BYOC) and an air-gapped install is expressed here, so the same
container images run everywhere with no code branching.

The validators below refuse to boot on an invalid combination. That is deliberate: a BYOC
install that silently phones home, or an air-gapped install that silently expects a network,
is a trust incident rather than a bug.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# --------------------------------------------------------------------------------------
# Deployment shape
# --------------------------------------------------------------------------------------


class DeploymentMode(StrEnum):
    """Who operates the control plane, and what it is allowed to talk to."""

    SAAS = "saas"
    """We operate it. Multi-tenant. Customer runs only the collector."""

    BYOC = "byoc"
    """Runs in the customer's own cloud account. We manage upgrades; their data never
    leaves their account. Single-tenant. Egress to us is opt-in and metadata only."""

    AIRGAP = "airgap"
    """Customer operates it in an isolated network. No egress to us under any
    circumstance. Licensing and vulnerability data arrive as offline bundles."""


class Tenancy(StrEnum):
    MULTI = "multi"
    SINGLE = "single"


class ProductMode(StrEnum):
    """Which product this install leads with.

    Two products are stacked in one console. ``ledger`` puts the agent action ledger
    first and leaves the accreditation screens reachable by URL; ``assurance`` restores
    the accreditation-era information architecture for the installs that bought it.

    This is a property of the install rather than of the member, because it decides what
    the product *is*, not what one person may see. A fresh install is a ledger install.
    """

    LEDGER = "ledger"
    ASSURANCE = "assurance"


class SecretsProvider(StrEnum):
    """Where runtime secrets come from. Differs per customer in BYOC."""

    ENV = "env"
    AWS_SECRETS_MANAGER = "aws_sm"
    AZURE_KEY_VAULT = "az_kv"
    GCP_SECRET_MANAGER = "gcp_sm"
    VAULT = "vault"


class ObjectStoreProvider(StrEnum):
    """Where accreditation packs and release artifacts are written."""

    LOCAL = "local"
    S3 = "s3"
    AZURE_BLOB = "azblob"
    GCS = "gcs"


class SigningProvider(StrEnum):
    """Where the private key used to sign packs and attestations lives.

    In BYOC the correct answer is the customer's own KMS. That way we are structurally
    incapable of signing on their behalf, which is a materially stronger trust story than
    a policy commitment not to.
    """

    LOCAL = "local"
    AWS_KMS = "aws_kms"
    AZURE_KEY_VAULT = "az_kv"
    GCP_KMS = "gcp_kms"


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- identity of this install ----
    deployment_mode: DeploymentMode = DeploymentMode.SAAS
    tenancy: Tenancy = Tenancy.MULTI
    product_mode: ProductMode = ProductMode.LEDGER
    instance_name: str = "local"
    environment: str = "development"
    version: str = "0.1.0"

    # Assurance-era surfaces that are off for a fresh install and reachable by URL.
    # Each name matches a capability flag the console reads from the bootstrap. Listed
    # rather than derived, so that turning one on is a deliberate act with a deployment
    # record rather than a side effect of some other setting. Comma-separated, like the
    # other list settings here.
    assurance_capabilities: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # In single-tenant modes every request is scoped to this organisation. The column and
    # the row-level security policy still exist, so the code path is identical to SaaS.
    default_org_slug: str = "default"

    # ---- database ----
    # Accepts a managed Postgres URL: RDS, Azure Database for PostgreSQL, Cloud SQL.
    #
    # `DATABASE_URL` is unprefixed on purpose (see NAMING.md): every platform-as-a-service
    # injects it under that name. `AAP_DATABASE_URL` is accepted too, because the prefix
    # is the rule everywhere else in this class and reaching for it is the obvious
    # mistake. pydantic-settings does not apply `env_prefix` to a field that declares a
    # validation alias, so without listing it here the prefixed name is read by nothing —
    # and since this field has a default, setting it would fail silently and point the
    # process at localhost instead. An integration suite migrated the wrong database for
    # a session that way.
    database_url: str = Field(
        default="postgresql+psycopg://aap:devonly@localhost:5432/aap",
        validation_alias=AliasChoices("DATABASE_URL", "AAP_DATABASE_URL"),
    )
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_statement_timeout_ms: int = 30_000
    # How long to wait for the server to accept a connection. Short on purpose: the
    # operating system's default is minutes, and an unreachable database must surface as
    # a named error on the login screen rather than as a request that never returns.
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    # ---- providers (the BYOC abstraction) ----
    secrets_provider: SecretsProvider = SecretsProvider.ENV
    secrets_prefix: str = "aap/"

    object_store: ObjectStoreProvider = ObjectStoreProvider.LOCAL
    object_store_bucket: str = "aap-artifacts"
    object_store_prefix: str = ""
    object_store_local_path: Path = Path("/var/lib/aap/artifacts")
    object_store_endpoint: str | None = None  # MinIO, or a private S3-compatible endpoint

    signing_provider: SigningProvider = SigningProvider.LOCAL
    signing_key_path: Path | None = Path("/run/secrets/signing.pem")
    signing_key_ref: str | None = None  # KMS key ARN, Key Vault id, or GCP resource name

    cloud_region: str | None = None

    # ---- identity ----
    # Generic OIDC, not a named provider. Entra, Okta, Keycloak and Auth0 all reduce to
    # an issuer, a discovery document and a JWKS, so supporting them is configuration
    # rather than four code paths. See D-034.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_cache_seconds: int = 3600
    # Set only for an issuer that does not publish a discovery document, or where it is
    # unreachable and the keys are mirrored internally. Normally left unset.
    oidc_jwks_url: str | None = None
    # Which claim names may carry the tenant, tried in order. The value found is looked
    # up in `identity_bindings`. The defaults cover a per-customer IdP (`iss`), Entra
    # (`tid`), Google Workspace (`hd`) and the org-aware IdPs (`org_id`).
    oidc_org_claims: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["org_id", "tid", "hd", "iss"]
    )
    # Asymmetric only, and an allowlist rather than "whatever the header says". Accepting
    # `none` or an HMAC algorithm here is the classic JWT forgery, because the public
    # verification key is by definition public and would then double as a signing secret.
    oidc_algorithms: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
    )
    oidc_leeway_seconds: int = 60  # clock skew between us and the IdP

    # ---- console sessions ----
    # Which sign-in methods exist is per-account data in `auth_providers`, not
    # configuration: see migration 0022. What stays here is the shape of the session the
    # server issues once a provider has verified someone.
    #
    # There is deliberately no development bypass any more. It used to be
    # `AAP_DEV_AUTH_BYPASS`, which made every request skip verification and every
    # permission check return early — and the console grew to depend on it, which is how
    # "the browser decides how authentication works" became load-bearing. Development
    # now uses a `development` row in `auth_providers`, refused outside
    # `AAP_ENVIRONMENT=development`, which issues a real session for a real member.
    session_cookie_name: str = "aap_session"
    session_idle_minutes: int = Field(default=60, ge=5, le=1440)
    """Sliding window. A renew extends this, never past the absolute ceiling below."""
    session_absolute_hours: int = Field(default=12, ge=1, le=720)
    """Hard ceiling from issue. Deprovisioning is only as fast as this in the worst case."""

    # ---- licensing ----
    # Offline, signed, file-based. No entitlement check may require network access,
    # because in air-gapped mode there is none and in BYOC an outage must not stop work.
    license_file: Path | None = None
    license_public_key_path: Path = Path("/etc/aap/license-pub.pem")

    # ---- model routing / AI gateway (policy authority, not the proxy itself) ----
    llm_gateway_enabled: bool = False
    llm_gateway_dev_permissive: bool = False
    router_snapshot_ttl_hours: int = Field(default=24, ge=1, le=168)

    # ---- Observe query service (control-plane BFF; never browser-accessible directly) ----
    observe_query_url: str | None = None
    observe_internal_service_token: str | None = None
    observe_query_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)

    # ---- Prompt workspace (control-plane BFF; never browser-accessible directly) ----
    prompt_service_url: str | None = None
    prompt_internal_service_token: str | None = None
    prompt_service_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    runtime_workload_bearer: str | None = Field(
        default=None,
        description="Server-side workload credential used for console-triggered runtime calls",
    )

    # ---- Evaluate workspace (control-plane BFF; never browser-accessible directly) ----
    evaluate_service_url: str | None = None
    evaluate_internal_service_token: str | None = None
    evaluate_service_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)

    # Probe gate defaults to advisory until suites prove stable in production (Q-D4-02).
    probe_gate_level: str = Field(default="advisory")
    probe_llm_judge_enabled: bool = False
    probe_llm_gate: bool = False
    probe_target_base_url: str | None = None
    model_catalogue_bundle_path: Path | None = None

    # ---- egress ----
    telemetry_enabled: bool = False
    telemetry_endpoint: str | None = None
    update_check_enabled: bool = False

    # ---- evidence and retention ----
    evidence_retention_days: int = 400
    evidence_max_text_bytes: int = 512  # enforced by test; see AGENTS.md rule 5
    evidence_partition_months_ahead: int = 3

    # ---- assurance behaviour ----
    materiality_ruleset: str = "default"
    prompt_drift_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    prompt_drift_material_threshold: float = 0.15
    prompt_drift_review_threshold: float = 0.05

    # ---- worker ----
    worker_concurrency: int = 4
    worker_poll_seconds: float = 1.0

    # ---- api ----
    api_root_path: str = ""
    # NoDecode keeps pydantic-settings from JSON-decoding the env var before validation.
    # Without it, AAP_CORS_ORIGINS="http://a,http://b" raised a SettingsError from the
    # env source and _split_comma_list below never ran, so the app could not boot under
    # Compose at all. The unit test missed it by passing the value as an init kwarg,
    # which bypasses the env source entirely.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    log_level: str = "INFO"
    log_format: str = "json"

    # ------------------------------------------------------------------
    # Validators — these are the interesting part of this file
    # ------------------------------------------------------------------

    @field_validator(
        "cors_origins",
        "oidc_org_claims",
        "oidc_algorithms",
        "assurance_capabilities",
        mode="before",
    )
    @classmethod
    def _split_comma_list(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _enforce_oidc_invariants(self) -> Settings:
        if self.oidc_issuer is None:
            return self

        # `https` is not pedantry here: the issuer URL is where the verification keys are
        # fetched from, so plaintext discovery means anyone on the path can serve their
        # own JWKS and mint tokens we would accept.
        if not self.oidc_issuer.startswith("https://") and self.environment != "development":
            raise ValueError("AAP_OIDC_ISSUER must be an https URL outside development")

        # Without an audience check, a token any other relying party obtained from the
        # same issuer is accepted here. That is the difference between authenticating a
        # user and accepting anything that issuer ever signed.
        if not self.oidc_audience:
            raise ValueError("AAP_OIDC_ISSUER requires AAP_OIDC_AUDIENCE")

        symmetric = [a for a in self.oidc_algorithms if not a.startswith(("RS", "ES", "PS"))]
        if symmetric:
            raise ValueError(f"AAP_OIDC_ALGORITHMS must be asymmetric; got {', '.join(symmetric)}")

        if self.tenancy is Tenancy.MULTI and not self.oidc_org_claims:
            raise ValueError("multi-tenant mode requires at least one AAP_OIDC_ORG_CLAIMS entry")

        return self

    @model_validator(mode="after")
    def _enforce_mode_invariants(self) -> Settings:
        mode = self.deployment_mode

        if mode is DeploymentMode.SAAS and self.tenancy is not Tenancy.MULTI:
            raise ValueError("saas mode requires AAP_TENANCY=multi")

        if mode is DeploymentMode.BYOC:
            if self.tenancy is not Tenancy.SINGLE:
                raise ValueError(
                    "byoc mode requires AAP_TENANCY=single — a customer-hosted control "
                    "plane serves exactly one organisation"
                )
            if self.telemetry_enabled and not self.telemetry_endpoint:
                raise ValueError("telemetry enabled but AAP_TELEMETRY_ENDPOINT is unset")

        if mode is DeploymentMode.AIRGAP:
            if self.tenancy is not Tenancy.SINGLE:
                raise ValueError("airgap mode requires AAP_TENANCY=single")
            if self.telemetry_enabled:
                raise ValueError("airgap mode forbids telemetry. Set AAP_TELEMETRY_ENABLED=false.")
            if self.update_check_enabled:
                raise ValueError(
                    "airgap mode forbids update checks. Set AAP_UPDATE_CHECK_ENABLED=false."
                )
            if self.signing_provider is not SigningProvider.LOCAL:
                raise ValueError(
                    "airgap mode requires AAP_SIGNING_PROVIDER=local — a cloud KMS is "
                    "unreachable from an isolated network"
                )
            if self.object_store not in (ObjectStoreProvider.LOCAL, ObjectStoreProvider.S3):
                raise ValueError(
                    "airgap mode supports object_store=local, or s3 against an on-premise "
                    "S3-compatible endpoint"
                )

        # Licensing is required wherever we are not the operator.
        if mode in (DeploymentMode.BYOC, DeploymentMode.AIRGAP) and self.license_file is None:
            raise ValueError(f"{mode} mode requires AAP_LICENSE_FILE")

        # Signing configuration must be internally consistent.
        if self.signing_provider is SigningProvider.LOCAL:
            if self.signing_key_path is None:
                raise ValueError("signing_provider=local requires AAP_SIGNING_KEY_PATH")
        elif self.signing_key_ref is None:
            raise ValueError(
                f"signing_provider={self.signing_provider} requires AAP_SIGNING_KEY_REF"
            )

        # Object store must know where to write.
        if self.object_store is ObjectStoreProvider.S3 and not self.object_store_bucket:
            raise ValueError("object_store=s3 requires AAP_OBJECT_STORE_BUCKET")

        return self

    @model_validator(mode="after")
    def _forbid_unsafe_development_flags(self) -> Settings:
        if self.llm_gateway_dev_permissive:
            if self.environment != "development":
                raise ValueError(
                    "AAP_LLM_GATEWAY_DEV_PERMISSIVE is only permitted when "
                    "AAP_ENVIRONMENT=development"
                )
            if self.deployment_mode in (DeploymentMode.BYOC, DeploymentMode.AIRGAP):
                raise ValueError(
                    "AAP_LLM_GATEWAY_DEV_PERMISSIVE is forbidden in byoc and airgap installs"
                )
        if self.oidc_issuer is None and self.environment != "development":
            # Allowed during initial bring-up, but it must be loud. The console can still
            # sign people in through an `auth_providers` row; what has no issuer here is
            # the *machine* credential path — the gateway, the SDKs and the collector.
            import logging

            logging.getLogger(__name__).warning(
                "No OIDC issuer configured — bearer-token callers (gateway, SDKs) will "
                "be rejected. Console sign-in is unaffected; it reads auth_providers."
            )
        return self

    @model_validator(mode="after")
    def _observe_service_config_is_complete(self) -> Settings:
        if bool(self.observe_query_url) != bool(self.observe_internal_service_token):
            raise ValueError(
                "AAP_OBSERVE_QUERY_URL and AAP_OBSERVE_INTERNAL_SERVICE_TOKEN "
                "must be configured together"
            )
        return self

    @model_validator(mode="after")
    def _prompt_service_config_is_complete(self) -> Settings:
        if bool(self.prompt_service_url) != bool(self.prompt_internal_service_token):
            raise ValueError(
                "AAP_PROMPT_SERVICE_URL and AAP_PROMPT_INTERNAL_SERVICE_TOKEN "
                "must be configured together"
            )
        return self

    @model_validator(mode="after")
    def _evaluate_service_config_is_complete(self) -> Settings:
        if bool(self.evaluate_service_url) != bool(self.evaluate_internal_service_token):
            raise ValueError(
                "AAP_EVALUATE_SERVICE_URL and AAP_EVALUATE_INTERNAL_SERVICE_TOKEN "
                "must be configured together"
            )
        return self

    # ------------------------------------------------------------------
    # Convenience predicates, so call sites read as intent not as comparison
    # ------------------------------------------------------------------

    @property
    def is_single_tenant(self) -> bool:
        return self.tenancy is Tenancy.SINGLE

    @property
    def egress_permitted(self) -> bool:
        """False in air-gapped mode. Guards every outbound call we make."""
        return self.deployment_mode is not DeploymentMode.AIRGAP

    @property
    def customer_operated(self) -> bool:
        return self.deployment_mode in (DeploymentMode.BYOC, DeploymentMode.AIRGAP)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
