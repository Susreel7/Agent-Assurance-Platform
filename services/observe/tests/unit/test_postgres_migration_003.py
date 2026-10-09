from __future__ import annotations

from pathlib import Path


def test_migration_003_exists_and_bounded() -> None:
    path = (
        Path(__file__).resolve().parents[2] / "observe" / "migrations" / "003_agent_execution.sql"
    )
    sql = path.read_text(encoding="utf-8")
    assert "agent_executions" in sql
    assert "projection_outbox" in sql
    assert "payload_access_audit" in sql
    assert "char_length(execution_id)" in sql
    assert "idx_ingest_manifests_source_wire" in sql
    assert "succeeded" in sql
