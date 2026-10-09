"""Deployment mode invariants.

Marked as invariant tests because these are not ordinary validation. A BYOC install that
silently phones home, or an air-gapped install that silently expects a network, is a
trust incident rather than a bug. The config must refuse to boot instead.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import (
    DeploymentMode,
    ObjectStoreProvider,
    SecretsProvider,
    Settings,
    SigningProvider,
    Tenancy,
)

pytestmark = pytest.mark.invariant


def settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+psycopg://aap:x@localhost:5432/aap",
        "environment": "test",
        # A developer's .env would otherwise supply fields this call leaves out, so the
        # test would assert against their machine instead of the declared defaults.
        "_env_file": None,
    }
    return Settings(**(base | kw))  # type: ignore[arg-type]


# ----------------------------------------------------------------- saas


def test_saas_defaults_are_valid() -> None:
    s = settings()
    assert s.deployment_mode is DeploymentMode.SAAS
    assert s.tenancy is Tenancy.MULTI
    assert s.egress_permitted
    assert not s.customer_operated
    assert not s.is_single_tenant


def test_saas_rejects_single_tenancy() -> None:
    with pytest.raises(ValidationError, match="saas mode requires"):
        settings(deployment_mode="saas", tenancy="single")


# ----------------------------------------------------------------- byoc


def test_byoc_requires_single_tenancy() -> None:
    with pytest.raises(ValidationError, match="byoc mode requires"):
        settings(
            deployment_mode="byoc",
            tenancy="multi",
            license_file="/etc/aap/license.aap",
        )


def test_byoc_requires_a_license_file() -> None:
    with pytest.raises(ValidationError, match="requires AAP_LICENSE_FILE"):
        settings(deployment_mode="byoc", tenancy="single")


def test_byoc_with_customer_kms_is_valid() -> None:
    """The configuration we actually want in production: the customer's own key."""
    s = settings(
        deployment_mode="byoc",
        tenancy="single",
        license_file="/etc/aap/license.aap",
        signing_provider="aws_kms",
        signing_key_ref="arn:aws:kms:eu-west-1:111122223333:key/abc",
        object_store="s3",
        object_store_bucket="acme-aap",
        secrets_provider="aws_sm",
    )
    assert s.customer_operated
    assert s.is_single_tenant
    assert s.egress_permitted  # BYOC may reach its own cloud APIs
    assert s.signing_provider is SigningProvider.AWS_KMS
    assert s.object_store is ObjectStoreProvider.S3
    assert s.secrets_provider is SecretsProvider.AWS_SECRETS_MANAGER


def test_byoc_telemetry_requires_an_endpoint() -> None:
    with pytest.raises(ValidationError, match="TELEMETRY_ENDPOINT"):
        settings(
            deployment_mode="byoc",
            tenancy="single",
            license_file="/etc/aap/license.aap",
            telemetry_enabled=True,
        )


# ----------------------------------------------------------------- airgap


def test_airgap_forbids_telemetry() -> None:
    with pytest.raises(ValidationError, match="airgap mode forbids telemetry"):
        settings(
            deployment_mode="airgap",
            tenancy="single",
            license_file="/etc/aap/license.aap",
            telemetry_enabled=True,
        )


def test_airgap_forbids_update_checks() -> None:
    with pytest.raises(ValidationError, match="forbids update checks"):
        settings(
            deployment_mode="airgap",
            tenancy="single",
            license_file="/etc/aap/license.aap",
            update_check_enabled=True,
        )


def test_airgap_forbids_a_cloud_kms() -> None:
    """A cloud KMS is unreachable from an isolated network, so accepting the setting
    would produce an install that appears healthy and cannot sign anything."""
    with pytest.raises(ValidationError, match=r"airgap mode requires.*local"):
        settings(
            deployment_mode="airgap",
            tenancy="single",
            license_file="/etc/aap/license.aap",
            signing_provider="aws_kms",
            signing_key_ref="arn:aws:kms:x",
        )


def test_airgap_forbids_azure_object_store() -> None:
    with pytest.raises(ValidationError, match="airgap mode supports"):
        settings(
            deployment_mode="airgap",
            tenancy="single",
            license_file="/etc/aap/license.aap",
            object_store="azblob",
            object_store_bucket="x",
        )


def test_airgap_permits_local_storage_and_blocks_egress() -> None:
    s = settings(
        deployment_mode="airgap",
        tenancy="single",
        license_file="/etc/aap/license.aap",
        object_store="local",
        signing_provider="local",
    )
    assert not s.egress_permitted
    assert s.customer_operated


def test_airgap_permits_onpremise_s3() -> None:
    """On-premise S3-compatible object storage is common in air-gapped estates."""
    s = settings(
        deployment_mode="airgap",
        tenancy="single",
        license_file="/etc/aap/license.aap",
        object_store="s3",
        object_store_bucket="aap",
        object_store_endpoint="https://objects.internal",
    )
    assert not s.egress_permitted


# ----------------------------------------------------------------- signing consistency


def test_kms_signing_requires_a_key_reference() -> None:
    with pytest.raises(ValidationError, match="requires AAP_SIGNING_KEY_REF"):
        settings(signing_provider="gcp_kms")


def test_local_signing_requires_a_key_path() -> None:
    with pytest.raises(ValidationError, match="requires AAP_SIGNING_KEY_PATH"):
        settings(signing_provider="local", signing_key_path=None)


def test_s3_requires_a_bucket() -> None:
    with pytest.raises(ValidationError, match="requires AAP_OBJECT_STORE_BUCKET"):
        settings(object_store="s3", object_store_bucket="")


# ----------------------------------------------------------------- dev-only flags


def test_there_is_no_auth_bypass_flag() -> None:
    """`AAP_DEV_AUTH_BYPASS` is gone, and this is what keeps it gone.

    It used to be here with two tests proving it could only be enabled in development,
    which was true and was not the problem. The problem was that it existed at all: it
    made every request skip verification and every permission check return early, and
    the console grew to depend on it, so "the browser decides how authentication works"
    became load-bearing. Development sign-in is now a `development` row in
    `auth_providers` that issues a real session for a real member — see
    `inv_dev_provider_requires_dev_mode`.

    `Settings` ignores unknown environment variables, so a stale `AAP_DEV_AUTH_BYPASS`
    in somebody's shell is inert rather than an error. That is the right behaviour and
    also the reason this test is worth having: nothing else would notice the field being
    quietly reintroduced.
    """
    configured = settings()

    assert not hasattr(configured, "dev_auth_bypass")
    assert "dev_auth_bypass" not in configured.model_dump()


def test_a_stale_bypass_variable_in_the_environment_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AAP_DEV_AUTH_BYPASS", "true")

    assert not hasattr(settings(), "dev_auth_bypass")


def test_cors_origins_accept_a_comma_separated_string() -> None:
    s = settings(cors_origins="http://a.test, http://b.test")
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_parse_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Through the env var, not an init kwarg.

    The test above passes `cors_origins` directly, which skips the environment source
    and so skipped the bug: pydantic-settings JSON-decodes list fields before validation
    and raised a SettingsError on the comma-separated form, meaning the app could not
    boot under Compose while this suite stayed green.
    """
    monkeypatch.setenv("AAP_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://aap:x@localhost:5432/aap")

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.cors_origins == ["http://localhost:5173", "http://localhost:3000"]


@pytest.mark.parametrize("name", ["DATABASE_URL", "AAP_DATABASE_URL"])
def test_the_database_url_is_read_under_either_name(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both spellings must reach the field, and the default must not win.

    `DATABASE_URL` is unprefixed because platforms inject it. `AAP_DATABASE_URL` matches
    every other setting in the class, so it is what anyone will try first. Declaring a
    validation alias switches `env_prefix` off for the field, so the prefixed name used
    to be read by nothing at all — and because the field has a default, nothing failed:
    the process silently used localhost. This asserts the default cannot win while an
    environment variable is present under either name.
    """
    url = "postgresql+psycopg://someone:secret@db.internal:6000/aap"
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    monkeypatch.setenv(name, url)

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.database_url == url


def test_a_single_origin_from_the_environment_is_still_a_list() -> None:
    s = settings(cors_origins="http://only.test")
    assert s.cors_origins == ["http://only.test"]


# ----------------------------------------------------------------- oidc


def test_an_issuer_without_an_audience_is_refused() -> None:
    """Without an audience check, any token that issuer ever signed for any other
    relying party is accepted here. That is not authentication."""
    with pytest.raises(ValidationError, match="requires AAP_OIDC_AUDIENCE"):
        settings(oidc_issuer="https://idp.test.example")


def test_a_plaintext_issuer_is_refused_outside_development() -> None:
    """The issuer URL is where verification keys come from, so plaintext discovery lets
    anyone on the path serve their own JWKS and mint tokens we would accept."""
    with pytest.raises(ValidationError, match="must be an https URL"):
        settings(oidc_issuer="http://idp.test.example", oidc_audience="aap-api")


def test_a_plaintext_issuer_is_allowed_in_development() -> None:
    s = settings(
        environment="development",
        oidc_issuer="http://localhost:8080/realms/aap",
        oidc_audience="aap-api",
    )
    assert s.oidc_issuer == "http://localhost:8080/realms/aap"


@pytest.mark.parametrize("algorithm", ["HS256", "none", "HS512"])
def test_symmetric_and_unsigned_algorithms_are_refused(algorithm: str) -> None:
    """The public verification key would double as a signing secret. This is the JWT
    forgery that keeps working, so the allowlist is validated rather than trusted."""
    with pytest.raises(ValidationError, match="must be asymmetric"):
        settings(
            oidc_issuer="https://idp.test.example",
            oidc_audience="aap-api",
            oidc_algorithms=algorithm,
        )


def test_org_claims_parse_from_a_comma_separated_string() -> None:
    s = settings(
        oidc_issuer="https://idp.test.example",
        oidc_audience="aap-api",
        oidc_org_claims="tid, org_id",
    )
    assert s.oidc_org_claims == ["tid", "org_id"]


def test_multi_tenant_requires_at_least_one_org_claim() -> None:
    """With no claim to map, a verified token says who the caller is and nothing about
    which tenant they act for — and there is no safe default."""
    with pytest.raises(ValidationError, match="AAP_OIDC_ORG_CLAIMS"):
        settings(
            oidc_issuer="https://idp.test.example",
            oidc_audience="aap-api",
            oidc_org_claims="",
        )


def test_single_tenant_does_not_need_an_org_claim() -> None:
    s = settings(
        deployment_mode=DeploymentMode.BYOC,
        tenancy=Tenancy.SINGLE,
        license_file="/etc/aap/license.jwt",
        oidc_issuer="https://idp.test.example",
        oidc_audience="aap-api",
        oidc_org_claims="",
    )
    assert s.oidc_org_claims == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
