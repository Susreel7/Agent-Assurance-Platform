"""Issue an offline license file.

Run by us, not by customers. The output is a signed document the customer drops onto
disk; their instance validates it with the bundled public key and never contacts us.

Format is ``<base64url payload>.<base64url signature>`` rather than a JWT, so an
operator can inspect the payload with ``base64 -d`` during an air-gapped install when
nobody can call support.

    python tools/issue_license.py \\
        --key secrets/byoc/license-key.pem \\
        --out secrets/byoc/license.aap \\
        --licensee "Acme Corp" --mode byoc --days 365 --max-agents 500 \\
        --modules router,observe,prompt,evaluate \\
        --module-limits '{"router":{"router_grace_days":30}}'
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SUITE_MODULE_IDS: tuple[str, ...] = ("router", "observe", "prompt", "evaluate")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _build_modules_block(
    modules_csv: str | None,
    limits_json: str,
) -> dict[str, dict[str, object]] | None:
    if modules_csv is None:
        return None
    enabled = {part.strip() for part in modules_csv.split(",") if part.strip()}
    unknown = enabled - set(SUITE_MODULE_IDS)
    if unknown:
        raise ValueError(f"unknown suite module(s): {', '.join(sorted(unknown))}")
    try:
        limits_map = json.loads(limits_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--module-limits is not valid JSON: {exc}") from exc
    if not isinstance(limits_map, dict):
        raise ValueError("--module-limits must be a JSON object")
    unknown_limit_modules = set(limits_map) - set(SUITE_MODULE_IDS)
    if unknown_limit_modules:
        raise ValueError(
            "limits provided for unknown suite module(s): "
            + ", ".join(sorted(unknown_limit_modules))
        )
    block: dict[str, dict[str, object]] = {}
    for module_id in SUITE_MODULE_IDS:
        module_limits = limits_map.get(module_id, {})
        if module_limits is None:
            module_limits = {}
        if not isinstance(module_limits, dict):
            raise ValueError(f"limits for {module_id!r} must be a JSON object")
        for key, value in module_limits.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError(f"limits for {module_id!r} contain an invalid name")
            if value is not None and not isinstance(value, str | int | float | bool):
                raise ValueError(f"limit {module_id}.{key} must be a scalar")
        block[module_id] = {
            "enabled": module_id in enabled,
            "limits": module_limits,
        }
    return block


def main() -> int:
    p = argparse.ArgumentParser(description="Issue an offline AAP license")
    p.add_argument("--key", required=True, type=Path, help="issuer private key (EC P-256 PEM)")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--licensee", required=True)
    p.add_argument("--instance-id", default="primary")
    p.add_argument("--mode", required=True, choices=["byoc", "airgap"])
    p.add_argument("--days", type=int, default=365)
    p.add_argument(
        "--max-agents",
        type=int,
        default=None,
        help="omit for unlimited; enforcement degrades to read-only, never blocks reads",
    )
    p.add_argument("--support-tier", default="standard")
    p.add_argument(
        "--features",
        default="registry,releases,evidence,graph,accreditation,attestation,portal",
        help="comma separated; '*' for everything",
    )
    p.add_argument(
        "--modules",
        default=None,
        help=(
            "comma-separated runtime-suite modules "
            "(router,observe,prompt,evaluate); omit for legacy licences without a modules block"
        ),
    )
    p.add_argument(
        "--module-limits",
        default="{}",
        help='JSON object of per-module limits, e.g. \'{"router":{"router_grace_days":30}}\'',
    )
    args = p.parse_args()

    if not args.key.exists():
        print(f"key not found: {args.key}", file=sys.stderr)
        return 1

    try:
        modules_block = _build_modules_block(args.modules, args.module_limits)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "licensee": args.licensee,
        "instance_id": args.instance_id,
        "deployment_mode": args.mode,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=args.days)).isoformat(),
        "max_agents": args.max_agents,
        "features": [f.strip() for f in args.features.split(",") if f.strip()],
        "support_tier": args.support_tier,
    }
    if modules_block is not None:
        payload["modules"] = modules_block

    # Sorted keys and no whitespace: the signature covers exact bytes, so the
    # serialisation has to be deterministic.
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    private = load_pem_private_key(args.key.read_bytes(), password=None)
    signature = private.sign(payload_bytes, ec.ECDSA(SHA256()))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(f"{b64url(payload_bytes)}.{b64url(signature)}")

    print(f"issued {args.out}")
    print(f"  licensee    {args.licensee}")
    print(f"  mode        {args.mode}")
    print(f"  expires     {payload['expires_at']}")
    print(f"  max agents  {args.max_agents if args.max_agents is not None else 'unlimited'}")
    if modules_block is not None:
        enabled = [mid for mid in SUITE_MODULE_IDS if modules_block[mid]["enabled"]]
        print(f"  modules     {', '.join(enabled) if enabled else '(none enabled)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
