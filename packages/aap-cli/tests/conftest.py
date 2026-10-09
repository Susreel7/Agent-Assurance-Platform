"""Shared fixtures for CLI tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def minimal_descriptor() -> dict[str, Any]:
    return {
        "aap_version": "0.1",
        "agent": {
            "urn": "urn:aap:acme:insurance:claims-processor",
            "version": "1.0.0",
        },
        "accountability": {
            "owning_team": "Insurance Automation",
            "accountable_person": "person:j.doe@acme.com",
        },
        "runtime": {"framework": "langgraph"},
    }


@pytest.fixture
def descriptors_dir(tmp_path: Path, minimal_descriptor: dict[str, Any]) -> Path:
    before = {**minimal_descriptor, "inference": {"temperature": 0.2}}
    after = {
        **minimal_descriptor,
        "agent": {**minimal_descriptor["agent"], "version": "1.0.1"},
        "inference": {"temperature": 0.9},
    }
    before_path = tmp_path / "before.yaml"
    after_path = tmp_path / "after.yaml"
    import yaml

    before_path.write_text(yaml.dump(before), encoding="utf-8")
    after_path.write_text(yaml.dump(after), encoding="utf-8")
    return tmp_path
