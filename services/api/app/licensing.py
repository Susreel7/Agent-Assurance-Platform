"""Offline entitlement.

A license is a signed JSON document on disk. It is never validated over the network,
because in air-gapped mode there is no network and in BYOC an outage on our side must not
stop a customer working. That constraint is the whole design.

Enforcement is deliberately soft: an expired or over-limit license degrades the install
to read-only rather than refusing to start. A governance platform that locks a customer
out of their own audit evidence during a contract renewal dispute would be indefensible.

Suite modules (``router``, ``observe``, ``prompt``, ``evaluate``) are declared in the
signed payload with per-module limits. Legacy free-form ``features`` remain for control-
plane capabilities outside the runtime suite.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from app.config import DeploymentMode, Settings, get_settings

SUITE_MODULE_IDS: tuple[str, ...] = ("router", "observe", "prompt", "evaluate")
DEFAULT_ROUTER_GRACE_DAYS = 30
type LicenseLimit = str | int | float | bool | None


class LicenseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SuiteModuleEntitlement:
    enabled: bool
    limits: dict[str, LicenseLimit]


@dataclass(frozen=True, slots=True)
class ModuleAccess:
    read: bool
    configure: bool
    ingest: bool
    infer: bool


@dataclass(frozen=True, slots=True)
class License:
    licensee: str
    instance_id: str
    deployment_mode: DeploymentMode
    issued_at: datetime
    expires_at: datetime
    max_agents: int | None
    features: frozenset[str]
    support_tier: str
    suite_modules: dict[str, SuiteModuleEntitlement]

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    @property
    def days_remaining(self) -> int:
        return max(0, (self.expires_at - datetime.now(UTC)).days)

    def permits(self, feature: str) -> bool:
        return feature in self.features or "*" in self.features


def _disabled_suite_modules() -> dict[str, SuiteModuleEntitlement]:
    return {
        module_id: SuiteModuleEntitlement(enabled=False, limits={})
        for module_id in SUITE_MODULE_IDS
    }


def _all_suite_modules_enabled() -> dict[str, SuiteModuleEntitlement]:
    return {
        module_id: SuiteModuleEntitlement(enabled=True, limits={}) for module_id in SUITE_MODULE_IDS
    }


UNLICENSED = License(
    licensee="unlicensed",
    instance_id="local",
    deployment_mode=DeploymentMode.SAAS,
    issued_at=datetime.now(UTC),
    expires_at=datetime.max.replace(tzinfo=UTC),
    max_agents=None,
    features=frozenset({"*"}),
    support_tier="none",
    suite_modules=_all_suite_modules_enabled(),
)
"""Used when we operate the install ourselves — entitlement is handled in billing, not here."""


def _parse_suite_modules(raw: object | None) -> dict[str, SuiteModuleEntitlement]:
    if raw is None:
        return _disabled_suite_modules()
    if not isinstance(raw, dict):
        raise LicenseError("license modules must be an object")
    unknown = set(raw) - set(SUITE_MODULE_IDS)
    if unknown:
        raise LicenseError(f"license contains unknown modules: {', '.join(sorted(unknown))}")

    parsed: dict[str, SuiteModuleEntitlement] = {}
    for module_id in SUITE_MODULE_IDS:
        entry = raw.get(module_id)
        if entry is None:
            parsed[module_id] = SuiteModuleEntitlement(enabled=False, limits={})
            continue
        if not isinstance(entry, dict):
            raise LicenseError(f"license module {module_id!r} must be an object")
        unknown_fields = set(entry) - {"enabled", "limits"}
        if unknown_fields:
            raise LicenseError(
                f"license module {module_id!r} has unknown fields: "
                f"{', '.join(sorted(unknown_fields))}"
            )
        enabled = entry.get("enabled", False)
        if not isinstance(enabled, bool):
            raise LicenseError(f"license module {module_id!r} enabled must be a boolean")
        limits_raw = entry.get("limits", {})
        if limits_raw is None:
            limits_raw = {}
        if not isinstance(limits_raw, dict):
            raise LicenseError(f"license module {module_id!r} limits must be an object")
        limits: dict[str, LicenseLimit] = {}
        for key, value in limits_raw.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise LicenseError(f"license module {module_id!r} has an invalid limit name")
            if value is not None and not isinstance(value, str | int | float | bool):
                raise LicenseError(f"license module {module_id!r} limit {key!r} must be a scalar")
            limits[key] = value
        parsed[module_id] = SuiteModuleEntitlement(enabled=enabled, limits=limits)
    return parsed


def _router_grace_days(limits: dict[str, LicenseLimit]) -> int:
    raw = limits.get("router_grace_days", DEFAULT_ROUTER_GRACE_DAYS)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return DEFAULT_ROUTER_GRACE_DAYS
    return max(0, min(raw, 365))


def suite_module_access(lic: License, module_id: str) -> ModuleAccess:
    """Effective capabilities for a suite module after expiry and grace rules."""
    ent = lic.suite_modules[module_id]
    if not ent.enabled:
        return ModuleAccess(read=False, configure=False, ingest=False, infer=False)

    if not lic.expired:
        return ModuleAccess(
            read=True,
            configure=True,
            ingest=module_id == "observe",
            infer=module_id == "router",
        )

    # Expired: reads stay up; observe ingest stays up; router inference only in grace;
    # new configuration and credential creation are blocked globally (see check_entitlement).
    read = True
    configure = False
    ingest = module_id == "observe"
    infer = False
    if module_id == "router":
        grace_end = lic.expires_at + timedelta(days=_router_grace_days(ent.limits))
        infer = datetime.now(UTC) < grace_end
    return ModuleAccess(read=read, configure=configure, ingest=ingest, infer=infer)


def blocks_credential_creation(lic: License | None = None) -> bool:
    """New workload keys and similar mutations when the licence is in read-only degradation."""
    active = lic or get_license()
    return active.expired


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _verify(payload: bytes, signature: bytes, public_key_pem: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    public_key = load_pem_public_key(public_key_pem)
    # Licences are ES256, same as everything else we sign. A non-EC key here is a build
    # error rather than a tampered licence, so it must not be reported as "invalid
    # licence" — that would send an operator looking in entirely the wrong place.
    if not isinstance(public_key, EllipticCurvePublicKey):
        raise TypeError("the bundled licence public key is not an EC key")

    try:
        public_key.verify(signature, payload, ec.ECDSA(SHA256()))
        return True
    except InvalidSignature:
        return False


def _license_datetime(data: dict[str, object], field: str) -> datetime:
    raw = data.get(field)
    if not isinstance(raw, str):
        raise LicenseError(f"license {field} must be an ISO datetime")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise LicenseError(f"license {field} must be an ISO datetime") from exc
    if value.tzinfo is None:
        raise LicenseError(f"license {field} must include a timezone")
    return value.astimezone(UTC)


def load_license(settings: Settings | None = None) -> License:
    """Parse and verify the license file.

    Format is two base64url segments separated by a dot: ``<payload>.<signature>``.
    Chosen over a full JWT because it needs no JWT library and an operator can inspect
    the payload with ``base64 -d``, which matters during an air-gapped install when
    nobody can call support.
    """
    s = settings or get_settings()

    if s.deployment_mode is DeploymentMode.SAAS:
        return UNLICENSED

    if s.license_file is None:
        raise LicenseError(f"{s.deployment_mode} mode requires AAP_LICENSE_FILE")

    path = Path(s.license_file)
    if not path.exists():
        raise LicenseError(f"license file not found: {path}")

    raw = path.read_text().strip()
    if raw.count(".") != 1:
        raise LicenseError("malformed license: expected <payload>.<signature>")

    payload_b64, signature_b64 = raw.split(".")
    payload = _b64url_decode(payload_b64)

    pub_path = Path(s.license_public_key_path)
    if not pub_path.exists():
        raise LicenseError(f"license public key not found: {pub_path}")

    if not _verify(payload, _b64url_decode(signature_b64), pub_path.read_bytes()):
        raise LicenseError("license signature is invalid")

    data = json.loads(payload)

    declared = DeploymentMode(data["deployment_mode"])
    if declared is not s.deployment_mode:
        raise LicenseError(
            f"license is issued for {declared} but this instance runs as {s.deployment_mode}"
        )

    issued_at = _license_datetime(data, "issued_at")
    expires_at = _license_datetime(data, "expires_at")
    if expires_at <= issued_at:
        raise LicenseError("license expires_at must be after issued_at")
    max_agents = data.get("max_agents")
    if max_agents is not None and (
        isinstance(max_agents, bool) or not isinstance(max_agents, int) or max_agents < 1
    ):
        raise LicenseError("license max_agents must be a positive integer or null")

    return License(
        licensee=data["licensee"],
        instance_id=data["instance_id"],
        deployment_mode=declared,
        issued_at=issued_at,
        expires_at=expires_at,
        max_agents=max_agents,
        features=frozenset(data.get("features", [])),
        support_tier=data.get("support_tier", "standard"),
        suite_modules=_parse_suite_modules(data.get("modules")),
    )


@lru_cache(maxsize=1)
def get_license() -> License:
    return load_license()


def reset_license_cache() -> None:
    get_license.cache_clear()


@dataclass(frozen=True, slots=True)
class EntitlementStatus:
    ok: bool
    read_only: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def check_entitlement(agent_count: int) -> EntitlementStatus:
    """Evaluated on startup and surfaced on the health endpoint and in the console banner.

    Note what this does *not* do: it never blocks reads, and it never blocks evidence
    ingest. Losing telemetry during a licensing dispute would corrupt the audit trail we
    exist to protect, which is a worse outcome than an unpaid invoice.
    """
    lic = get_license()
    reasons: list[str] = []
    warnings: list[str] = []

    if lic.expired:
        reasons.append(f"license expired on {lic.expires_at.date().isoformat()}")
    elif lic.days_remaining <= 30:
        warnings.append(f"license expires in {lic.days_remaining} days")

    if lic.max_agents is not None and agent_count > lic.max_agents:
        reasons.append(f"agent count {agent_count} exceeds licensed maximum {lic.max_agents}")
    elif lic.max_agents is not None and agent_count > int(lic.max_agents * 0.9):
        warnings.append(f"agent count {agent_count} is near the licensed maximum {lic.max_agents}")

    return EntitlementStatus(
        ok=not reasons,
        read_only=bool(reasons),
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
