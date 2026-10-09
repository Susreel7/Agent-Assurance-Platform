"""Schema validation command tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from aap_cli.commands import validate as validate_cmd
from aap_cli.config import CliConfig
from aap_cli.loader import validate_descriptor


def test_validate_accepts_minimal(minimal_descriptor: dict) -> None:
    result = validate_descriptor(minimal_descriptor)
    assert result.valid is True
    assert result.issues == ()


def test_validate_rejects_missing_required() -> None:
    result = validate_descriptor({"aap_version": "0.1"})
    assert result.valid is False
    assert len(result.issues) >= 1
    assert all(i.path and i.message for i in result.issues)


def test_validate_command_exit_codes(tmp_path: Path, minimal_descriptor: dict) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(yaml.dump(minimal_descriptor), encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.dump({"aap_version": "0.1"}), encoding="utf-8")
    cfg = CliConfig(base_url="http://test", org_id=None, token=None, json_output=False)

    assert validate_cmd.run(good, cfg) == 0
    assert validate_cmd.run(bad, cfg) == 1


def test_validate_json_shape(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, minimal_descriptor: dict
) -> None:
    path = tmp_path / "d.yaml"
    path.write_text(yaml.dump(minimal_descriptor), encoding="utf-8")
    cfg = CliConfig(base_url="http://test", org_id=None, token=None, json_output=True)
    assert validate_cmd.run(path, cfg) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["issues"] == []
