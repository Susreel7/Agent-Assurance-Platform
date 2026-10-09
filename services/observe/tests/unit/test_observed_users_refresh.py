from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from observe.db import repository as repo


def test_refresh_observed_user_replaces_counters_from_aggregate() -> None:
    org = uuid4()
    project = uuid4()
    user_id = "user-1"
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = {
        "execution_count": 2,
        "generation_count": 5,
        "tool_count": 3,
        "sdk_count": 1,
        "mcp_tool_count": 4,
        "first_seen_at": None,
    }

    repo.refresh_observed_user_from_executions(
        conn, org_id=org, project_id=project, user_id=user_id
    )

    assert cursor.execute.call_count == 2
    insert_sql = cursor.execute.call_args_list[1].args[0]
    insert_params = cursor.execute.call_args_list[1].args[1]
    assert "INSERT INTO observe.observed_users" in insert_sql
    assert "execution_count = EXCLUDED.execution_count" in insert_sql
    assert insert_params[3] == 2
    assert insert_params[4] == 5
    assert insert_params[7] == 4
