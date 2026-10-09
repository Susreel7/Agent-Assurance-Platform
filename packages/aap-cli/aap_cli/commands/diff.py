"""``aap diff`` — semantic descriptor delta for engineers reviewing a change."""

from __future__ import annotations

import sys
from pathlib import Path

from aap_cli.config import CliConfig
from aap_cli.loader import DescriptorLoadError, load_descriptor
from aap_cli.releases_bridge import OfflineDependencyError, diff_descriptors
from aap_cli.render import render_diff, render_error


def run(before_path: Path, after_path: Path, config: CliConfig) -> int:
    try:
        after = load_descriptor(after_path)
        before = load_descriptor(before_path) if before_path else None
    except DescriptorLoadError as exc:
        render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
        return 1

    try:
        diff = diff_descriptors(before, after)
    except OfflineDependencyError as exc:
        render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
        return 1

    render_diff(diff, as_json=config.json_output, stream=sys.stdout)
    return 0
