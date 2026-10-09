"""Generate the local development keys, without needing openssl on PATH.

`make bootstrap` shells out to `openssl ecparam`, which is fine on a developer's Mac or
in CI and not fine on Windows, where openssl is usually absent. The keys are ordinary
EC P-256 keypairs, and `cryptography` is already a dependency because the signing and
licensing providers use it, so there is nothing openssl was contributing here except a
command that sometimes does not exist.

Idempotent: an existing key is left alone. Regenerating the signing key would orphan
every batch signature already in the database, and regenerating the licence key would
invalidate the licence issued from it.

    python tools/bootstrap_secrets.py            # under services/api or repo root
    python tools/bootstrap_secrets.py --force    # replace them anyway
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

REPO_ROOT = Path(__file__).resolve().parent.parent
SIGNING_KEY = REPO_ROOT / "secrets" / "signing.pem"
ROUTER_CONFIG_PUB = REPO_ROOT / "secrets" / "router-config-pub.pem"
LICENSE_KEY = REPO_ROOT / "secrets" / "byoc" / "license-key.pem"
LICENSE_PUB = REPO_ROOT / "secrets" / "byoc" / "license-pub.pem"


def write_private_key(path: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    # Best effort: Windows ignores the mode bits, and on POSIX this is the 0600 that
    # openssl's chmod in the Makefile was doing.
    path.chmod(0o600)


def write_public_key(private_path: Path, public_path: Path) -> None:
    key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace keys that already exist (invalidates existing signatures)",
    )
    args = parser.parse_args(argv)

    made = []
    if args.force or not SIGNING_KEY.exists():
        write_private_key(SIGNING_KEY)
        made.append(str(SIGNING_KEY.relative_to(REPO_ROOT)))

    if args.force or not LICENSE_KEY.exists():
        write_private_key(LICENSE_KEY)
        made.append(str(LICENSE_KEY.relative_to(REPO_ROOT)))

    if args.force or not ROUTER_CONFIG_PUB.exists():
        write_public_key(SIGNING_KEY, ROUTER_CONFIG_PUB)
        made.append(str(ROUTER_CONFIG_PUB.relative_to(REPO_ROOT)))

    if args.force or not LICENSE_PUB.exists():
        write_public_key(LICENSE_KEY, LICENSE_PUB)
        made.append(str(LICENSE_PUB.relative_to(REPO_ROOT)))

    for path in made:
        print(f"generated {path}")
    if not made:
        print("keys already present, nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
