from __future__ import annotations

from uuid import uuid4

from observe.db import repository as repo


class _FakeCursor:
    def __init__(self) -> None:
        self.row: dict | None = None
        self.updates: list[tuple] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        if "SELECT content_fingerprint" in sql and self.row is not None:
            return
        if "INSERT INTO observe.span_idempotency" in sql:
            self.row = {
                "content_fingerprint": params[4] if params else "",
                "is_terminal": params[6] if params else False,
            }
        if "UPDATE observe.span_idempotency" in sql:
            assert params is not None
            self.row = {"content_fingerprint": params[0], "is_terminal": True}
            self.updates.append(params)

    def fetchone(self) -> dict | None:
        return self.row


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self.cur


def test_terminal_replacement() -> None:
    conn = _FakeConn()
    org, proj, manifest = uuid4(), uuid4(), uuid4()
    conn.cur.row = {"content_fingerprint": "sha256:old", "is_terminal": False}
    action = repo.apply_span_identity(
        conn,  # type: ignore[arg-type]
        org_id=org,
        project_id=proj,
        trace_id="t" * 32,
        span_id="s" * 16,
        fingerprint="sha256:new",
        manifest_id=manifest,
        is_terminal=True,
    )
    assert action == "replaced"
    assert conn.cur.updates
