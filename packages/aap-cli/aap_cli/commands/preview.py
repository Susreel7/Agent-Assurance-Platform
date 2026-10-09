"""``aap preview`` — CI release gate (online API or offline local verdict)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

from aap_cli.client import AapClient, AuthError, CliError, NetworkError
from aap_cli.config import CliConfig
from aap_cli.loader import DescriptorLoadError, load_descriptor
from aap_cli.releases_bridge import OfflineDependencyError, preview_offline
from aap_cli.render import render_error, render_verdict


def _verdict_to_dict(verdict: Any) -> dict[str, Any]:
    if hasattr(verdict, "model_dump"):
        return cast(dict[str, Any], verdict.model_dump(mode="json"))
    return cast(dict[str, Any], dict(verdict))


def run(
    before_path: Path | None,
    after_path: Path,
    config: CliConfig,
    *,
    offline: bool,
    transport: Any | None = None,
) -> int:
    try:
        after = load_descriptor(after_path)
        before = load_descriptor(before_path) if before_path else None
    except DescriptorLoadError as exc:
        render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
        return 1

    if offline:
        try:
            verdict = preview_offline(before, after)
        except OfflineDependencyError as exc:
            render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
            return 1
        payload = _verdict_to_dict(verdict)
        render_verdict(
            payload,
            as_json=config.json_output,
            stream=sys.stdout,
            local_unratified=True,
        )
        return 0 if payload.get("allowed") else 2

    try:
        with AapClient(config, transport=transport) as client:
            payload = client.preview_release(before, after)
    except AuthError as exc:
        render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
        return 1
    except (NetworkError, CliError) as exc:
        render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
        return 1

    render_verdict(payload, as_json=config.json_output, stream=sys.stdout)
    return 0 if payload.get("allowed") else 2
