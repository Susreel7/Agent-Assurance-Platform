"""Emit a deterministic, production-shaped FOSS Remediation Agent execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_env() -> dict[str, str]:
    values = dict(os.environ)
    path = REPO_ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values.setdefault(key.strip(), value.strip())
    return values


def any_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (dict, list)):
        return {"stringValue": json.dumps(value, separators=(",", ":"), sort_keys=True)}
    return {"stringValue": str(value)}


def attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"key": key, "value": any_value(value)}
        for key, value in values.items()
        if value is not None
    ]


def identity(run_key: str, label: str, size: int) -> str:
    return hashlib.sha256(f"{run_key}:{label}".encode()).hexdigest()[:size]


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def span(
    *,
    trace_id: str,
    run_key: str,
    label: str,
    parent: str | None,
    start_ns: int,
    start_seconds: float,
    duration_seconds: float,
    observation_type: str,
    name: str,
    values: dict[str, Any] | None = None,
    events: list[tuple[float, str, dict[str, Any]]] | None = None,
    failed: bool = False,
) -> dict[str, Any]:
    span_id = identity(run_key, label, 16)
    item: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start_ns + int(start_seconds * 1_000_000_000)),
        "endTimeUnixNano": str(start_ns + int((start_seconds + duration_seconds) * 1_000_000_000)),
        "attributes": attributes(
            {
                "aap.observation.type": observation_type,
                "gen_ai.operation.name": (
                    "invoke_agent"
                    if observation_type == "agent"
                    else "chat"
                    if observation_type == "generation"
                    else "execute_tool"
                    if observation_type in {"tool", "mcp"}
                    else "workflow"
                ),
                **(values or {}),
            }
        ),
        "status": {"code": 2 if failed else 1, "message": "test failure" if failed else ""},
    }
    if parent:
        item["parentSpanId"] = identity(run_key, parent, 16)
    if events:
        item["events"] = [
            {
                "timeUnixNano": str(start_ns + int(at * 1_000_000_000)),
                "name": event_name,
                "attributes": attributes({"aap.event.type": event_name, **event_attributes}),
            }
            for at, event_name, event_attributes in events
        ]
    return item


def build_payload(
    *,
    run_key: str,
    org_id: str,
    project_id: str,
    now_ns: int,
) -> tuple[dict[str, Any], str, str]:
    trace_id = identity(run_key, "trace", 32)
    execution_id = f"foss-{identity(run_key, 'execution', 24)}"
    session_id = f"foss-session-{datetime.now(UTC):%Y%m%d}"
    common = {"aap.execution.id": execution_id}
    spans = [
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="root",
            parent=None,
            start_ns=now_ns,
            start_seconds=0,
            duration_seconds=48.2,
            observation_type="agent",
            name="FOSS Remediation Agent",
            values={
                **common,
                "aap.execution.type": "agent",
                "aap.trigger.type": "web_ui",
                "aap.repository.ref": "nexaguard/agent-runtime",
                "aap.repository.branch": "fix/CVE-2026-1842",
                "aap.repository.commit_sha": "7c91f12",
                "aap.framework.name": "langgraph",
                "aap.framework.version": "1.0.6",
            },
            events=[
                (0.0, "execution.started", {"aap.observation.type": "agent"}),
                (
                    47.9,
                    "evidence.attached",
                    {"aap.event.artifact": "remediation.patch", "aap.observation.type": "event"},
                ),
            ],
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="user-request",
            parent="root",
            start_ns=now_ns,
            start_seconds=0.1,
            duration_seconds=0.1,
            observation_type="event",
            name="User Request",
            values={
                **common,
                "aap.observation.input": {
                    "repository": "nexaguard/agent-runtime",
                    "request": "Remediate CVE-2026-1842 and prove tests pass.",
                },
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="orchestrator",
            parent="root",
            start_ns=now_ns,
            start_seconds=0.3,
            duration_seconds=0.8,
            observation_type="node",
            name="Orchestrator",
            values={
                **common,
                "aap.graph.name": "foss-remediation",
                "aap.graph.version": "2026.09.16",
                "aap.graph.node.id": "orchestrator",
                "aap.graph.node.path": "root/orchestrator",
                "aap.graph.step": 1,
            },
            events=[
                (
                    1.0,
                    "state.transition",
                    {
                        "aap.observation.type": "state_transition",
                        "aap.state.from": "orchestrator",
                        "aap.state.to": "analysis_agent",
                        "aap.graph.branch": "repository_has_lockfile",
                    },
                )
            ],
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="analysis",
            parent="root",
            start_ns=now_ns,
            start_seconds=1.2,
            duration_seconds=6.4,
            observation_type="node",
            name="Analysis Agent",
            values={
                **common,
                "aap.graph.node.id": "analysis_agent",
                "aap.graph.node.path": "root/analysis_agent",
                "aap.graph.step": 2,
                "aap.node.input_state": {"cve": "CVE-2026-1842", "ecosystem": "python"},
                "aap.node.output_state": {
                    "package": "urllib3",
                    "installed": "2.1.0",
                    "fixed": "2.2.2",
                },
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="retrieval",
            parent="analysis",
            start_ns=now_ns,
            start_seconds=1.4,
            duration_seconds=1.2,
            observation_type="retrieval",
            name="Repository Retrieval",
            values={
                **common,
                "gen_ai.retrieval.query": "urllib3 constraints and dependency lockfiles",
                "aap.retrieval.documents": ["pyproject.toml", "requirements-lock.txt"],
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="llm-analysis",
            parent="analysis",
            start_ns=now_ns,
            start_seconds=2.7,
            duration_seconds=2.1,
            observation_type="generation",
            name="Claude vulnerability analysis",
            values={
                **common,
                "gen_ai.provider.name": "anthropic",
                "gen_ai.request.model": "claude-sonnet-5",
                "gen_ai.response.model": "claude-sonnet-5-20260901",
                "gen_ai.request.temperature": 0,
                "gen_ai.usage.input_tokens": 2911,
                "gen_ai.usage.output_tokens": 571,
                "gen_ai.usage.reasoning_tokens": 184,
                "gen_ai.usage.cost": 160_000,
                "gen_ai.system_instructions": (
                    "You are a senior software supply-chain engineer. Identify the smallest "
                    "safe remediation and cite repository evidence."
                ),
                "gen_ai.input.messages": [
                    {"role": "user", "content": "Assess CVE-2026-1842 in this repository."}
                ],
                "gen_ai.output.messages": [
                    {
                        "role": "assistant",
                        "content": "Upgrade urllib3 to 2.2.2 and regenerate the lockfile.",
                    }
                ],
                "gen_ai.response.finish_reasons": ["stop"],
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="vulnerability",
            parent="root",
            start_ns=now_ns,
            start_seconds=2.0,
            duration_seconds=3.1,
            observation_type="tool",
            name="Vulnerability Scanner",
            values={
                **common,
                "gen_ai.tool.name": "osv.scan",
                "aap.tool.type": "security_scanner",
                "aap.tool.arguments": {"lockfile": "requirements-lock.txt", "severity": "high"},
                "gen_ai.tool.call.result": {
                    "vulnerability": "CVE-2026-1842",
                    "affected": True,
                    "fixed_version": "2.2.2",
                },
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="coding",
            parent="root",
            start_ns=now_ns,
            start_seconds=8.0,
            duration_seconds=18.6,
            observation_type="node",
            name="Coding Agent",
            values={
                **common,
                "aap.graph.node.id": "coding_agent",
                "aap.graph.node.path": "root/coding_agent",
                "aap.graph.step": 3,
                "aap.graph.iteration": 2,
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="llm-code",
            parent="coding",
            start_ns=now_ns,
            start_seconds=8.2,
            duration_seconds=4.2,
            observation_type="generation",
            name="Claude patch generation",
            values={
                **common,
                "gen_ai.provider.name": "anthropic",
                "gen_ai.request.model": "claude-sonnet-5",
                "gen_ai.usage.input_tokens": 3482,
                "gen_ai.usage.output_tokens": 911,
                "gen_ai.usage.cost": 260_000,
                "aap.prompt.version": "foss-coder@17",
                "gen_ai.system_instructions": (
                    "Generate a minimal dependency remediation. Never expose credentials. "
                    "Return a patch and verification plan."
                ),
                "gen_ai.input.messages": [
                    {
                        "role": "developer",
                        "content": "Preserve Python 3.12 compatibility and existing constraints.",
                    },
                    {
                        "role": "user",
                        "content": "Upgrade urllib3 and update the lockfile.",
                    },
                ],
                "gen_ai.output.messages": [
                    {
                        "role": "assistant",
                        "content": "Prepared a two-file patch and targeted regression tests.",
                    }
                ],
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="cursor-sdk",
            parent="coding",
            start_ns=now_ns,
            start_seconds=12.5,
            duration_seconds=9.1,
            observation_type="sdk",
            name="Cursor SDK",
            values={
                **common,
                "aap.sdk.name": "cursor",
                "aap.sdk.version": "2.5.0",
                "aap.sdk.operation": "apply_patch",
                "aap.sdk.arguments": {
                    "files": ["pyproject.toml", "requirements-lock.txt"],
                    "strategy": "minimal",
                },
                "aap.sdk.result": {"files_changed": 2, "insertions": 3, "deletions": 3},
                "aap.request.id": "cursor-demo-1",
                "aap.response.id": "cursor-demo-response-1",
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="filesystem",
            parent="cursor-sdk",
            start_ns=now_ns,
            start_seconds=12.8,
            duration_seconds=3.6,
            observation_type="tool",
            name="Filesystem write",
            values={
                **common,
                "gen_ai.tool.name": "filesystem.write",
                "aap.tool.type": "filesystem",
                "aap.tool.permissions": "workspace:write",
                "aap.tool.arguments": {"path": "requirements-lock.txt"},
                "gen_ai.tool.call.result": {"bytes": 18_442, "status": "written"},
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="git",
            parent="cursor-sdk",
            start_ns=now_ns,
            start_seconds=16.6,
            duration_seconds=0.6,
            observation_type="tool",
            name="Git diff",
            values={
                **common,
                "gen_ai.tool.name": "git.diff",
                "aap.tool.type": "repository",
                "gen_ai.tool.call.result": {"files": 2, "binary": False},
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="tests-failed",
            parent="cursor-sdk",
            start_ns=now_ns,
            start_seconds=17.4,
            duration_seconds=1.7,
            observation_type="tool",
            name="Test Runner · attempt 1",
            failed=True,
            values={
                **common,
                "gen_ai.tool.name": "pytest",
                "aap.tool.type": "shell",
                "aap.retry.attempt": 1,
                "error.type": "AssertionError",
                "error.message": "lockfile hash changed",
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="retry",
            parent="coding",
            start_ns=now_ns,
            start_seconds=19.2,
            duration_seconds=0.2,
            observation_type="retry",
            name="Retry Coding Agent",
            values={
                **common,
                "aap.retry.target": "coding_agent",
                "aap.retry.attempt": 2,
                "aap.retry.reason": "lockfile hash changed",
                "aap.retry.backoff_ms": 100,
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="tests-success",
            parent="cursor-sdk",
            start_ns=now_ns,
            start_seconds=19.5,
            duration_seconds=1.7,
            observation_type="tool",
            name="Test Runner · attempt 2",
            values={
                **common,
                "gen_ai.tool.name": "pytest",
                "aap.tool.type": "shell",
                "aap.retry.attempt": 2,
                "gen_ai.tool.call.result": {"passed": 126, "failed": 0, "skipped": 3},
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="approval",
            parent="root",
            start_ns=now_ns,
            start_seconds=27.0,
            duration_seconds=0.5,
            observation_type="human_approval",
            name="Security approval",
            values={
                **common,
                "aap.approval.id": "approval-foss-1",
                "aap.approval.action": "merge_remediation",
                "aap.approval.decision": "approved",
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="mcp-client",
            parent="root",
            start_ns=now_ns,
            start_seconds=28.0,
            duration_seconds=1.3,
            observation_type="mcp",
            name="MCP GitHub evidence",
            values={
                **common,
                "aap.mcp.server": "github-enterprise",
                "aap.mcp.method": "tools/call",
                "aap.mcp.role": "client",
                "aap.mcp.request_id": "mcp-foss-1",
                "aap.mcp.arguments": {"tool": "create_check_run", "repository": "agent-runtime"},
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="evaluation",
            parent="root",
            start_ns=now_ns,
            start_seconds=30.0,
            duration_seconds=4.7,
            observation_type="evaluation",
            name="Evaluator",
            values={
                **common,
                "aap.evaluation.name": "remediation-quality",
                "aap.evaluation.score": 0.97,
                "aap.evaluation.verdict": "pass",
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="a2a",
            parent="root",
            start_ns=now_ns,
            start_seconds=35.0,
            duration_seconds=0.7,
            observation_type="a2a",
            name="A2A Compliance Evidence Agent",
            values={
                **common,
                "aap.a2a.target_agent_id": "compliance-evidence-agent",
                "aap.a2a.target_trace_id": identity(run_key, "evidence-trace", 32),
                "aap.a2a.protocol": "a2a",
            },
        ),
        span(
            trace_id=trace_id,
            run_key=run_key,
            label="final",
            parent="root",
            start_ns=now_ns,
            start_seconds=47.4,
            duration_seconds=0.6,
            observation_type="node",
            name="Final Response",
            values={
                **common,
                "aap.graph.node.id": "final_response",
                "aap.graph.node.path": "root/final_response",
                "aap.graph.step": 6,
                "aap.observation.output": {
                    "status": "remediated",
                    "files_changed": 2,
                    "tests_passed": 126,
                    "evidence": ["osv.scan", "git.diff", "pytest", "evaluation"],
                },
            },
        ),
    ]
    resource = {
        "attributes": attributes(
            {
                "service.name": "foss-remediation-agent",
                "service.version": "2.7.4",
                "deployment.environment.name": "production",
                "gen_ai.agent.id": "foss-remediation",
                "gen_ai.agent.name": "FOSS Remediation Agent",
                "gen_ai.agent.version": "2.7.4",
                "aap.organization.id": org_id,
                "aap.project.id": project_id,
                "aap.session.id": session_id,
                "aap.user.session_id": session_id,
                "aap.user.id": "priya.sharma",
                "aap.actor.id": "priya.sharma",
                "aap.actor.type": "user",
                "aap.invocation.source": "web_ui",
                "aap.invocation.application": "NexaGuard Console",
                "aap.invocation.client": "web",
                "aap.request.id": f"request-{identity(run_key, 'request', 12)}",
                "cloud.region": "us-east-1",
                "process.runtime.name": "python",
                "aap.sampling.rate": 1.0,
            }
        )
    }
    return (
        {
            "resourceSpans": [
                {
                    "resource": resource,
                    "scopeSpans": [
                        {
                            "scope": {"name": "nexaguard.demo", "version": "1.0.0"},
                            "spans": spans,
                        }
                    ],
                }
            ]
        },
        execution_id,
        trace_id,
    )


def main() -> int:
    env = read_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-key",
        default=datetime.now(UTC).strftime("foss-%Y%m%dT%H%M%S"),
        help="Stable key used to derive trace/span IDs; reuse to test idempotency.",
    )
    parser.add_argument(
        "--collector-url",
        default=env.get("NEXAGUARD_OTEL_ENDPOINT")
        or env.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or f"http://localhost:{env.get('OTLP_PORT', '4318')}",
    )
    parser.add_argument("--api-url", default=env.get("AAP_API_URL", "http://localhost:8000"))
    parser.add_argument("--configure-full-capture", action="store_true")
    args = parser.parse_args()

    org_id = env.get("RUNTIME_ORG_ID", "")
    project_id = env.get("RUNTIME_PROJECT_ID", "")
    token = env.get("RUNTIME_WORKLOAD_BEARER", "")
    if not all((org_id, project_id, token)):
        raise SystemExit(
            "RUNTIME_ORG_ID, RUNTIME_PROJECT_ID, and RUNTIME_WORKLOAD_BEARER are required. "
            "Run tools/bootstrap_runtime.py first."
        )

    user_headers = {"Content-Type": "application/json", "X-Org-Id": org_id}
    user_token = env.get("NEXAGUARD_USER_BEARER")
    if user_token:
        user_headers["Authorization"] = f"Bearer {user_token}"
    if args.configure_full_capture:
        status, detail = request(
            "PATCH",
            f"{args.api_url.rstrip('/')}/v1/workload-credentials/projects/{project_id}",
            headers=user_headers,
            body={
                "trace_capture_mode": "full",
                "payload_encryption_key_ref": "local:demo-fernet",
                "payload_retention_days": 30,
            },
        )
        if status >= 300:
            raise SystemExit(f"could not enable full capture ({status}): {detail.decode()}")

    now_ns = time.time_ns() - 50_000_000_000
    payload, execution_id, trace_id = build_payload(
        run_key=args.run_key,
        org_id=org_id,
        project_id=project_id,
        now_ns=now_ns,
    )
    collector = args.collector_url.rstrip("/")
    if not collector.endswith("/v1/traces"):
        collector += "/v1/traces"
    status, detail = request(
        "POST",
        collector,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        body=payload,
    )
    if status >= 300:
        raise SystemExit(f"collector rejected demo trace ({status}): {detail.decode()}")

    execution_url = (
        f"{args.api_url.rstrip('/')}/v1/observe/projects/{project_id}/executions/{execution_id}"
    )
    observed = False
    for _ in range(30):
        verify_status, _ = request("GET", execution_url, headers=user_headers)
        if verify_status == 200:
            observed = True
            break
        time.sleep(1)
    if not observed:
        raise SystemExit("trace accepted but execution projection was not queryable within 30s")

    print(f"execution_id={execution_id}")
    print(f"trace_id={trace_id}")
    print(f"ui=http://localhost:5173/observe/executions/{execution_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
