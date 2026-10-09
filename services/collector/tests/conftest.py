from __future__ import annotations

from pathlib import Path

import pytest

from collector.config import CaptureMode, Settings
from collector.metrics import CollectorMetrics
from collector.spool import SpoolStore


@pytest.fixture
def tmp_spool(tmp_path: Path) -> SpoolStore:
    return SpoolStore(tmp_path / "spool", disk_quota_bytes=10 * 1024 * 1024)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        spool_dir=str(tmp_path / "spool"),
        capture_mode=CaptureMode.DIGEST,
        workload_bearer_token="wk-test-token",
        observe_ingest_url="http://observe.test/v1/traces",
        disk_quota_bytes=10 * 1024 * 1024,
    )


@pytest.fixture
def metrics() -> CollectorMetrics:
    return CollectorMetrics()
