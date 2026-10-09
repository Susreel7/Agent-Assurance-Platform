from __future__ import annotations

from collector.config import Settings


def test_observe_logs_url_derived_from_traces() -> None:
    settings = Settings(observe_ingest_url="http://observe.test:8080/v1/traces")
    assert settings.observe_logs_ingest_url == "http://observe.test:8080/v1/logs"


def test_observe_logs_url_explicit_override() -> None:
    settings = Settings(
        observe_ingest_url="http://observe.test/v1/traces",
        observe_logs_ingest_url="http://custom/v1/logs",
    )
    assert settings.observe_logs_ingest_url == "http://custom/v1/logs"
