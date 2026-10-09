from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from adapter import app as adapter_app


class FakeSpan:
    def __init__(self) -> None:
        self.name = ""
        self.attributes: dict[str, object] = {}
        self.ended = False

    def update_name(self, name: str) -> None:
        self.name = name

    def set_attributes(self, attributes: dict[str, object]) -> None:
        self.attributes.update(attributes)

    def set_status(self, _: object) -> None:
        return None

    def end(self) -> None:
        self.ended = True


class FakeProcess:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def exchange(self, message: dict[str, Any]) -> dict[str, Any]:
        self.messages.append(message)
        if message["method"] == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "tools": [
                        {"name": "allowed", "inputSchema": {"type": "object"}},
                        {"name": "denied", "inputSchema": {"type": "object"}},
                    ]
                },
            }
        return {"jsonrpc": "2.0", "id": message["id"], "result": {"content": []}}


class FakeRuntime:
    def __init__(self, decisions: dict[str, dict[str, Any]]) -> None:
        self.decisions = decisions
        self.process = FakeProcess()
        self.processes = {"test-mcp": self.process}

    async def close(self) -> None:
        return None

    async def authenticate(self, _: str) -> dict[str, Any]:
        return {"active": True, "modules": ["router"], "scopes": ["mcp:invoke"]}

    async def decide(self, _: str, __: str, capability_name: str) -> dict[str, Any]:
        return self.decisions.get(
            capability_name,
            {"allowed": False, "requires_approval": False, "reason_code": "no_grant"},
        )

    def process_for(self, _: str) -> FakeProcess:
        return self.process

    async def record_usage(self, *_: object, **__: object) -> None:
        return None


def request(method: str, *, content: str = "{}") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            "name": "allowed",
            "arguments": {"content": content},
        },
    }


def test_denied_tool_never_reaches_upstream() -> None:
    fake = FakeRuntime({})
    with TestClient(adapter_app.app) as client:
        adapter_app.runtime = fake
        response = client.post(
            "/v1/mcp/test-mcp",
            headers={"Authorization": "Bearer aap_workload_test"},
            json=request("tools/call"),
        )

    assert response.status_code == 403
    assert response.json()["error"]["data"]["reason_code"] == "no_grant"
    assert fake.process.messages == []


def test_secret_is_blocked_after_policy_allow() -> None:
    fake = FakeRuntime(
        {
            "allowed": {
                "allowed": True,
                "requires_approval": False,
                "reason_code": "granted",
            }
        }
    )
    with TestClient(adapter_app.app) as client:
        adapter_app.runtime = fake
        response = client.post(
            "/v1/mcp/test-mcp",
            headers={"Authorization": "Bearer aap_workload_test"},
            json=request("tools/call", content="password=correct-horse-battery-staple"),
        )

    assert response.status_code == 403
    assert response.json()["error"]["data"]["reason_code"] == "secret_detected"
    assert "correct-horse" not in response.text
    assert fake.process.messages == []


def test_json_escaped_secret_is_blocked_before_upstream() -> None:
    fake = FakeRuntime(
        {
            "allowed": {
                "allowed": True,
                "requires_approval": False,
                "reason_code": "granted",
            }
        }
    )
    payload = (
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
        '{"name":"allowed","arguments":{"content":'
        '"sk-\\u0070roj-012345678901234567890123456789"}}}'
    )
    with TestClient(adapter_app.app) as client:
        adapter_app.runtime = fake
        response = client.post(
            "/v1/mcp/test-mcp",
            headers={
                "Authorization": "Bearer aap_workload_test",
                "Content-Type": "application/json",
            },
            content=payload,
        )

    assert response.status_code == 403
    assert response.json()["error"]["data"]["reason_code"] == "secret_detected"
    assert fake.process.messages == []


def test_tool_list_contains_only_granted_capabilities() -> None:
    fake = FakeRuntime(
        {
            "allowed": {
                "allowed": True,
                "requires_approval": False,
                "reason_code": "granted",
            }
        }
    )
    with TestClient(adapter_app.app) as client:
        adapter_app.runtime = fake
        response = client.post(
            "/v1/mcp/test-mcp",
            headers={"Authorization": "Bearer aap_workload_test"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert response.status_code == 200
    assert [tool["name"] for tool in response.json()["result"]["tools"]] == ["allowed"]


def test_unauthenticated_list_never_reaches_upstream() -> None:
    class RejectingRuntime(FakeRuntime):
        async def authenticate(self, _: str) -> dict[str, Any]:
            raise adapter_app.AdapterError(
                "invalid Platform Key",
                reason="invalid_platform_key",
                status=401,
            )

    fake = RejectingRuntime({})
    with TestClient(adapter_app.app) as client:
        adapter_app.runtime = fake
        response = client.post(
            "/v1/mcp/test-mcp",
            headers={"Authorization": "Bearer invalid"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert response.status_code == 401
    assert fake.process.messages == []


def test_trace_metadata_attributes_tool_without_payload() -> None:
    span = FakeSpan()
    adapter_app._finish_span(
        span,
        server_slug="test-mcp",
        rpc_method="tools/call",
        tool_name="allowed",
        reason="granted",
        outcome="allowed",
        response_status=200,
        latency_ms=1.5,
        identity={
            "project_id": "project-1",
            "agent_id": "agent-1",
            "member_id": "member-1",
            "workload_credential_id": "credential-1",
            "environment": "production",
        },
    )

    assert span.ended is True
    assert span.name == "mcp.tools/call"
    assert span.attributes["gen_ai.tool.name"] == "allowed"
    assert span.attributes["aap.actor.id"] == "agent-1"
    assert span.attributes["aap.user.id"] == "member-1"
    assert not any("content" in key or "argument" in key for key in span.attributes)
