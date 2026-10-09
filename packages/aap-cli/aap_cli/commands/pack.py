"""``aap pack`` — download the current accreditation pack artifact."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from aap_cli.client import AapClient, AuthError, CliError, NetworkError
from aap_cli.config import CliConfig
from aap_cli.render import render_error, render_pack_result

_DIGEST_RE = re.compile(r"^sha256:([a-f0-9]{64})$")


def _pick_current_pack(packs: list[dict[str, object]]) -> dict[str, object] | None:
    current = [p for p in packs if p.get("is_current")]
    if not current:
        return packs[0] if packs else None
    json_packs = [p for p in current if p.get("format") == "json"]
    return json_packs[0] if json_packs else current[0]


def _safe_filename(accreditation_id: str, fmt: str) -> str:
    ext = "json" if fmt == "json" else fmt
    return f"accreditation-{accreditation_id}-pack.{ext}"


def run(
    accreditation_id: str,
    config: CliConfig,
    *,
    output_dir: Path | None = None,
    transport: Any | None = None,
) -> int:
    try:
        UUID(accreditation_id)
    except ValueError:
        render_error(
            f"accreditation id must be a UUID, got {accreditation_id!r}",
            as_json=config.json_output,
            stream=sys.stdout,
        )
        return 1

    try:
        with AapClient(config, transport=transport) as client:
            packs = client.list_packs(accreditation_id)
            if not packs:
                render_error(
                    "no packs found for this accreditation",
                    as_json=config.json_output,
                    stream=sys.stdout,
                )
                return 1
            pack = _pick_current_pack(packs)
            assert pack is not None
            pack_uri = str(pack.get("pack_uri", ""))
            pack_digest = str(pack.get("pack_digest", ""))
            fmt = str(pack.get("format", "json"))
            body = client.download_bytes(pack_uri)
    except AuthError as exc:
        render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
        return 1
    except (NetworkError, CliError) as exc:
        render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
        return 1

    dest_dir = output_dir or Path.cwd()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _safe_filename(accreditation_id, fmt)
    dest.write_bytes(body)

    digest = pack_digest
    match = _DIGEST_RE.match(pack_digest)
    if match:
        computed = hashlib.sha256(body).hexdigest()
        if computed != match.group(1):
            render_error(
                "downloaded bytes do not match pack_digest from the platform",
                as_json=config.json_output,
                stream=sys.stdout,
            )
            return 1

    render_pack_result(str(dest.resolve()), digest, as_json=config.json_output, stream=sys.stdout)
    return 0
