"""``aap validate`` — schema check only, no platform call."""

from __future__ import annotations

import sys
from pathlib import Path

from aap_cli.config import CliConfig
from aap_cli.loader import DescriptorLoadError, load_descriptor, validate_descriptor
from aap_cli.render import render_error, render_validation


def run(path: Path, config: CliConfig) -> int:
    try:
        document = load_descriptor(path)
    except DescriptorLoadError as exc:
        render_error(str(exc), as_json=config.json_output, stream=sys.stdout)
        return 1

    result = validate_descriptor(document)
    render_validation(result, as_json=config.json_output, stream=sys.stdout)
    return 0 if result.valid else 1
