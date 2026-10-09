from __future__ import annotations

from pathlib import Path

import pytest

from observe.config import Settings, reset_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    root = tmp_path / "objects"
    root.mkdir()
    return Settings(
        database_url="postgresql://unused:5432/unused",
        run_migrations_on_startup=False,
        object_store_root=str(root),
        internal_service_token="test-token",
        introspection_url="http://introspect.test/v1/workload/introspect",
    )
