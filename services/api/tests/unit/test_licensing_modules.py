"""Signed suite-module entitlements and GET /v1/modules."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_public_key,
)

from app.config import DeploymentMode, Settings, get_settings
from app.domains.modules import service as modules_service
from app.domains.modules.schemas import ModuleCapability
from app.licensing import (
    DEFAULT_ROUTER_GRACE_DAYS,
    License,
    SuiteModuleEntitlement,
    blocks_credential_creation,
    load_license,
    reset_license_cache,
    suite_module_access,
)


def _sign_payload(payload: dict[str, object], private_pem: bytes) -> str:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    private = load_pem_private_key(private_pem, password=None)
    signature = private.sign(body, ec.ECDSA(SHA256()))
    import base64

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    return f"{b64url(body)}.{b64url(signature)}"


@pytest.fixture
def license_keypair(tmp_path: Path) -> tuple[Path, Path]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    key_path = tmp_path / "license-key.pem"
    pub_path = tmp_path / "license-pub.pem"
    key_path.write_bytes(private_pem)
    pub_path.write_bytes(public_pem)
    return key_path, pub_path


def _license_file(
    tmp_path: Path,
    keypair: tuple[Path, Path],
    *,
    expires_at: datetime,
    modules: dict[str, dict[str, object]] | None,
    features: list[str] | None = None,
) -> Path:
    _, pub_path = keypair
    private_pem = keypair[0].read_bytes()
    payload: dict[str, object] = {
        "licensee": "Test Co",
        "instance_id": "primary",
        "deployment_mode": "byoc",
        "issued_at": datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
        "expires_at": expires_at.isoformat(),
        "max_agents": 10,
        "features": features if features is not None else ["registry", "evidence"],
        "support_tier": "standard",
    }
    if modules is not None:
        payload["modules"] = modules
    lic_path = tmp_path / "license.aap"
    lic_path.write_text(_sign_payload(payload, private_pem))
    load_pem_public_key(pub_path.read_bytes())
    return lic_path


@pytest.fixture
def byoc_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    license_keypair: tuple[Path, Path],
):
    lic_path = _license_file(
        tmp_path,
        license_keypair,
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        modules={
            "router": {"enabled": True, "limits": {"router_grace_days": 14}},
            "observe": {"enabled": True, "limits": {}},
            "prompt": {"enabled": False, "limits": {}},
            "evaluate": {"enabled": True, "limits": {"max_experiments": 5}},
        },
    )
    _, pub_path = license_keypair
    settings = Settings(
        deployment_mode=DeploymentMode.BYOC,
        tenancy="single",
        license_file=lic_path,
        license_public_key_path=pub_path,
        environment="development",
    )
    get_settings.cache_clear()
    reset_license_cache()
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.licensing.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: settings)
    yield settings
    get_settings.cache_clear()
    reset_license_cache()


def test_legacy_license_without_modules_disables_suite(
    tmp_path: Path, license_keypair: tuple[Path, Path]
) -> None:
    lic_path = _license_file(
        tmp_path,
        license_keypair,
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        modules=None,
        features=["registry", "*"],
    )
    settings = Settings(
        deployment_mode=DeploymentMode.BYOC,
        tenancy="single",
        license_file=lic_path,
        license_public_key_path=license_keypair[1],
        environment="development",
    )
    get_settings.cache_clear()
    reset_license_cache()
    lic = load_license(settings)
    assert lic.permits("anything")
    assert not lic.suite_modules["router"].enabled
    assert lic.features == frozenset({"registry", "*"})


def test_suite_module_access_when_active(byoc_settings: Settings) -> None:
    lic = load_license(byoc_settings)
    router = suite_module_access(lic, "router")
    observe = suite_module_access(lic, "observe")
    assert router.read and router.configure and router.infer and not router.ingest
    assert observe.read and observe.configure and observe.ingest and not observe.infer


def test_expired_preserves_reads_and_observe_ingest(byoc_settings: Settings) -> None:
    active = load_license(byoc_settings)
    lic = License(
        licensee=active.licensee,
        instance_id=active.instance_id,
        deployment_mode=active.deployment_mode,
        issued_at=active.issued_at,
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        max_agents=active.max_agents,
        features=active.features,
        support_tier=active.support_tier,
        suite_modules=active.suite_modules,
    )
    observe = suite_module_access(lic, "observe")
    evaluate = suite_module_access(lic, "evaluate")
    assert observe.read and observe.ingest and not observe.configure
    assert evaluate.read and not evaluate.configure


def test_router_inference_grace_uses_signed_limit(byoc_settings: Settings) -> None:
    base = load_license(byoc_settings)
    now = datetime.now(UTC)
    recently_expired = License(
        licensee=base.licensee,
        instance_id=base.instance_id,
        deployment_mode=base.deployment_mode,
        issued_at=base.issued_at,
        expires_at=now - timedelta(days=1),
        max_agents=base.max_agents,
        features=base.features,
        support_tier=base.support_tier,
        suite_modules=base.suite_modules,
    )
    within = suite_module_access(recently_expired, "router")
    assert within.infer

    past_grace = License(
        licensee=base.licensee,
        instance_id=base.instance_id,
        deployment_mode=base.deployment_mode,
        issued_at=base.issued_at,
        expires_at=now - timedelta(days=30),
        max_agents=base.max_agents,
        features=base.features,
        support_tier=base.support_tier,
        suite_modules=base.suite_modules,
    )
    after_grace = suite_module_access(past_grace, "router")
    assert after_grace.read and not after_grace.infer and not after_grace.configure


def test_router_default_grace_when_limit_omitted() -> None:
    modules = {
        mid: SuiteModuleEntitlement(enabled=True, limits={})
        for mid in ("router", "observe", "prompt", "evaluate")
    }
    lic = License(
        licensee="x",
        instance_id="primary",
        deployment_mode=DeploymentMode.BYOC,
        issued_at=datetime(2024, 1, 1, tzinfo=UTC),
        expires_at=datetime(2024, 1, 1, tzinfo=UTC),
        max_agents=None,
        features=frozenset(),
        support_tier="standard",
        suite_modules=modules,
    )
    edge = lic.expires_at + timedelta(days=DEFAULT_ROUTER_GRACE_DAYS - 1)
    # Monkeypatch time by constructing expires relative to now
    lic_fresh = License(
        licensee=lic.licensee,
        instance_id=lic.instance_id,
        deployment_mode=lic.deployment_mode,
        issued_at=datetime.now(UTC) - timedelta(days=400),
        expires_at=datetime.now(UTC) - timedelta(days=1),
        max_agents=None,
        features=frozenset(),
        support_tier="standard",
        suite_modules=modules,
    )
    assert suite_module_access(lic_fresh, "router").infer
    _ = edge  # documentation anchor for default grace length


def test_blocks_credential_creation_when_expired(byoc_settings: Settings) -> None:
    lic = load_license(byoc_settings)
    assert not blocks_credential_creation(lic)
    expired = License(
        licensee=lic.licensee,
        instance_id=lic.instance_id,
        deployment_mode=lic.deployment_mode,
        issued_at=lic.issued_at,
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        max_agents=lic.max_agents,
        features=lic.features,
        support_tier=lic.support_tier,
        suite_modules=lic.suite_modules,
    )
    assert blocks_credential_creation(expired)


def test_manifest_revision_is_deterministic(byoc_settings: Settings) -> None:
    first = modules_service.build_effective_manifest()
    second = modules_service.build_effective_manifest()
    assert first.revision == second.revision
    assert first.revision.startswith("sha256:")
    assert first.modules["router"].base_path == "/router"
    assert not first.modules["prompt"].enabled
    assert first.modules["router"].access.infer


def test_saas_enables_all_modules() -> None:
    get_settings.cache_clear()
    reset_license_cache()
    settings = Settings(deployment_mode=DeploymentMode.SAAS, tenancy="multi")
    lic = load_license(settings)
    assert all(ent.enabled for ent in lic.suite_modules.values())


def test_require_module_capability_raises_for_disabled(byoc_settings: Settings) -> None:
    with pytest.raises(modules_service.ModuleNotEntitledError):
        modules_service.assert_module_capability("prompt", ModuleCapability.READ)


@pytest.mark.asyncio
async def test_get_modules_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    locked = Settings(deployment_mode=DeploymentMode.SAAS, tenancy="multi")
    get_settings.cache_clear()
    reset_license_cache()
    monkeypatch.setattr("app.config.get_settings", lambda: locked)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: locked)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/modules")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_modules_returns_manifest(byoc_settings: Settings) -> None:
    """The manifest a licensed, authenticated caller sees.

    Authentication is overridden rather than supplied. It used to be waved through by
    `AAP_DEV_AUTH_BYPASS` on the settings object, and by an `X-Org-Id` header that was
    never a credential — both are gone, and what this test is actually about is the
    licence, not how the caller proved who they are.
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import Authenticated, authenticate
    from app.auth import Principal
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[authenticate] = lambda: Authenticated(
        principal=Principal(subject="user-1", issuer="https://idp.example", email=None),
        claims={},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/modules")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"].startswith("sha256:")
    assert set(body["modules"]) == {"router", "observe", "prompt", "evaluate"}


def test_issue_license_modules_deterministic(
    tmp_path: Path, license_keypair: tuple[Path, Path]
) -> None:
    import subprocess
    import sys

    out = tmp_path / "out.aap"
    repo_root = next(
        (
            parent
            for parent in Path(__file__).resolve().parents
            if (parent / "tools" / "issue_license.py").exists()
        ),
        None,
    )
    if repo_root is None:
        pytest.skip("the API-only container does not mount the repository tools directory")
    cmd = [
        sys.executable,
        str(repo_root / "tools" / "issue_license.py"),
        "--key",
        str(license_keypair[0]),
        "--out",
        str(out),
        "--licensee",
        "Acme",
        "--mode",
        "byoc",
        "--days",
        "10",
        "--modules",
        "router,observe",
        "--module-limits",
        '{"router":{"router_grace_days":7}}',
    ]
    subprocess.run(cmd, check=True, cwd=repo_root)
    payload_b64 = out.read_text().strip().split(".")[0]
    import base64

    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    assert payload["modules"]["router"]["enabled"] is True
    assert payload["modules"]["prompt"]["enabled"] is False
    assert payload["modules"]["router"]["limits"]["router_grace_days"] == 7
