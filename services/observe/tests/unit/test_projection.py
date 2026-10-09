from __future__ import annotations

from uuid import uuid4

import pytest

from observe.worker.projection import _run_report


def test_projection_is_content_free_and_correlated() -> None:
    execution_id = str(uuid4())
    agent_id = str(uuid4())
    report = _run_report(
        {
            "execution_id": execution_id,
            "agent_id": agent_id,
            "agent_version_id": str(uuid4()),
            "environment_id": "production",
            "started_at": "2026-09-16T08:00:00+00:00",
            "ended_at": "2026-09-16T08:00:05+00:00",
            "status": "succeeded",
            "span_count": 9,
            "tool_count": 3,
            "retry_count": 1,
            "model": "claude-test",
            "tokens_in": 10,
            "tokens_out": 5,
            "total_cost_micros": 42,
            "trace_id": "t" * 32,
            "secret_prompt": "must never project",
        }
    )
    assert report["run_id"] == execution_id
    assert report["agent_id"] == agent_id
    assert report["step_count"] == 9
    assert report["tool_call_count"] == 3
    assert report["reported_by"] == "observe-projection"
    assert "secret_prompt" not in report
    assert "prompt" not in str(report)


def test_projection_rejects_uncorrelatable_identity() -> None:
    with pytest.raises(ValueError, match="UUID"):
        _run_report(
            {
                "execution_id": "not-a-uuid",
                "agent_id": "not-a-uuid",
                "started_at": "2026-09-16T08:00:00+00:00",
                "ended_at": "2026-09-16T08:00:05+00:00",
                "status": "succeeded",
            }
        )
