"""Diff command requires the offline extra (aap-api)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aap_cli.commands import diff as diff_cmd
from aap_cli.config import CliConfig


def test_diff_produces_changes(descriptors_dir: Path) -> None:
    pytest.importorskip("app.domains.releases.differ")
    cfg = CliConfig(base_url="http://test", org_id=None, token=None, json_output=False)
    code = diff_cmd.run(
        descriptors_dir / "before.yaml",
        descriptors_dir / "after.yaml",
        cfg,
    )
    assert code == 0
