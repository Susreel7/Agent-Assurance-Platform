from __future__ import annotations

from uuid import uuid4

from observe.db import postgres


class FakeCursor:
    def __init__(self, statements: list[tuple[str, object]]) -> None:
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.statements.append((sql, params))


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []
        self.committed = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.statements)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_tenant_and_worker_context_are_transaction_local(monkeypatch) -> None:
    connections: list[FakeConnection] = []

    def fake_connect(*_args, **_kwargs) -> FakeConnection:
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(postgres.psycopg, "connect", fake_connect)
    org_id = uuid4()
    project_id = uuid4()
    with postgres.connect("postgresql://test", organization_id=org_id, project_id=project_id):
        pass
    with postgres.connect("postgresql://test", worker=True):
        pass

    assert connections[0].statements[0][1] == (str(org_id), str(project_id))
    assert "app.observe_worker" in connections[1].statements[0][0]
    assert all(connection.committed and connection.closed for connection in connections)
