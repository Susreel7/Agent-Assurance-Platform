from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

log = logging.getLogger("aap.mcp_adapter")

API_BASE = os.getenv("MCP_CONTROL_PLANE_URL", "http://api:8000").rstrip("/")
MAX_REQUEST_BYTES = int(os.getenv("MCP_MAX_REQUEST_BYTES", str(2 << 20)))
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("MCP_UPSTREAM_TIMEOUT_SECONDS", "120"))

DEFAULT_SERVERS: dict[str, dict[str, Any]] = {
    "demo-mcp": {"command": "python", "args": ["/servers/demo_server.py"]},
}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github_token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{40,255})\b")),
    ("openai_api_key", re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,255}\b")),
    ("anthropic_api_key", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,255}\b")),
    ("google_api_key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b")),
    ("jwt", re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    (
        "authorization_bearer",
        re.compile(
            rb"\bauthorization\s*[\"']?\s*[:=]\s*[\"']?bearer\s+[A-Za-z0-9._~+/-]{12,}",
            re.IGNORECASE,
        ),
    ),
    (
        "azure_storage_key",
        re.compile(rb"\bAccountKey\s*=\s*[A-Za-z0-9+/]{40,}={0,2}", re.IGNORECASE),
    ),
    (
        "credential_in_url",
        re.compile(rb"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]{1,128}:[^/\s@]{4,256}@"),
    ),
    (
        "labelled_secret",
        re.compile(
            rb"\b(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|password|passwd|secret[_ -]?key)"
            rb"\s*[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._~+/-]{8,512}",
            re.IGNORECASE,
        ),
    ),
)


class AdapterError(Exception):
    def __init__(self, message: str, *, reason: str, status: int = 503) -> None:
        super().__init__(message)
        self.reason = reason
        self.status = status


def _server_config() -> dict[str, dict[str, Any]]:
    raw = os.getenv("MCP_STDIO_SERVERS_JSON")
    if not raw:
        return DEFAULT_SERVERS
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("MCP_STDIO_SERVERS_JSON must be an object")
    return parsed


def _child_environment() -> dict[str, str]:
    # The shipped server is synthetic and needs an interpreter, not a credential.
    # A prefix allow-list that forwarded integration secrets lived here previously;
    # this tree does not ship one. Add a prefix only for a server you operate yourself.
    return {
        "PATH": os.getenv("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


@dataclass
class StdioProcess:
    slug: str
    definition: dict[str, Any]
    process: asyncio.subprocess.Process | None = None

    def __post_init__(self) -> None:
        self.lock = asyncio.Lock()

    async def close(self) -> None:
        if self.process is None or self.process.returncode is not None:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=3)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()

    async def exchange(self, message: dict[str, Any]) -> dict[str, Any] | None:
        async with self.lock:
            await self._ensure_started()
            assert self.process is not None
            assert self.process.stdin is not None
            assert self.process.stdout is not None

            wire = json.dumps(message, separators=(",", ":")).encode() + b"\n"
            self.process.stdin.write(wire)
            await self.process.stdin.drain()
            if message.get("id") is None:
                return None

            try:
                line = await asyncio.wait_for(
                    self.process.stdout.readline(),
                    timeout=UPSTREAM_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                await self.close()
                raise AdapterError(
                    "MCP server timed out",
                    reason="upstream_timeout",
                    status=504,
                ) from exc
            if not line:
                return_code = self.process.returncode
                self.process = None
                raise AdapterError(
                    f"MCP server stopped before responding ({return_code})",
                    reason="upstream_stopped",
                )
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AdapterError(
                    "MCP server returned invalid JSON",
                    reason="invalid_upstream_response",
                    status=502,
                ) from exc
            if not isinstance(response, dict):
                raise AdapterError(
                    "MCP server returned a non-object response",
                    reason="invalid_upstream_response",
                    status=502,
                )
            return response

    async def _ensure_started(self) -> None:
        if self.process is not None and self.process.returncode is None:
            return
        command = self.definition.get("command")
        args = self.definition.get("args", [])
        if not isinstance(command, str) or not command:
            raise AdapterError(
                "MCP server has no approved deployment command",
                reason="deployment_not_configured",
            )
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise AdapterError(
                "MCP server deployment arguments are invalid",
                reason="deployment_not_configured",
            )
        self.process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=_child_environment(),
        )


@dataclass
class UsageCounter:
    call_count: int = 0
    denied_count: int = 0
    approval_count: int = 0
    error_count: int = 0
    latencies_ms: list[int] | None = None

    def add(
        self,
        *,
        denied: bool,
        approval: bool,
        error: bool,
        latency_ms: float,
    ) -> None:
        self.call_count += 1
        self.denied_count += int(denied)
        self.approval_count += int(approval)
        self.error_count += int(error)
        if self.latencies_ms is None:
            self.latencies_ms = []
        if len(self.latencies_ms) < 4096:
            self.latencies_ms.append(max(0, round(latency_ms)))

    def merge(self, other: UsageCounter) -> None:
        self.call_count += other.call_count
        self.denied_count += other.denied_count
        self.approval_count += other.approval_count
        self.error_count += other.error_count
        samples = (self.latencies_ms or []) + (other.latencies_ms or [])
        self.latencies_ms = samples[:4096]

    def p95(self) -> int | None:
        samples = sorted(self.latencies_ms or [])
        if not samples:
            return None
        index = max(0, min(len(samples) - 1, (95 * len(samples) + 99) // 100 - 1))
        return samples[index]


class Runtime:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        self.processes = {
            slug: StdioProcess(slug=slug, definition=definition)
            for slug, definition in _server_config().items()
        }
        self.usage_bearer = os.getenv("MCP_USAGE_BEARER", "").strip()
        self.usage: dict[
            tuple[str, str, str, str | None, str | None],
            UsageCounter,
        ] = {}
        self.usage_lock = asyncio.Lock()
        self.usage_task = asyncio.create_task(self._usage_loop())
        self.telemetry_provider: TracerProvider | None = None
        otlp_endpoint = os.getenv("MCP_OTLP_TRACES_ENDPOINT", "").strip()
        if otlp_endpoint:
            self.telemetry_provider = TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": "agent-assurance-mcp-adapter",
                        "service.version": "0.1.0",
                    }
                )
            )
            self.telemetry_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            )
            self.tracer = self.telemetry_provider.get_tracer("agent-assurance.mcp")
        else:
            self.tracer = trace.get_tracer("agent-assurance.mcp")

    async def close(self) -> None:
        self.usage_task.cancel()
        await asyncio.gather(self.usage_task, return_exceptions=True)
        await self.flush_usage()
        await asyncio.gather(*(process.close() for process in self.processes.values()))
        await self.http.aclose()
        if self.telemetry_provider is not None:
            await asyncio.to_thread(self.telemetry_provider.shutdown)

    def process_for(self, slug: str) -> StdioProcess:
        process = self.processes.get(slug)
        if process is None:
            raise AdapterError(
                "MCP server is not deployed on this adapter",
                reason="deployment_not_configured",
                status=404,
            )
        return process

    async def authenticate(self, authorization: str) -> dict[str, Any]:
        response = await self.http.post(
            f"{API_BASE}/v1/workload-credentials/-/introspect",
            headers={"Authorization": authorization},
        )
        if response.status_code == 401:
            raise AdapterError("Invalid Platform Key", reason="invalid_platform_key", status=401)
        if not response.is_success:
            raise AdapterError(
                "Workload identity service is unavailable",
                reason="identity_unavailable",
            )
        identity = response.json()
        scopes = set(identity.get("scopes") or [])
        modules = set(identity.get("modules") or [])
        if not identity.get("active") or "router" not in modules or "mcp:invoke" not in scopes:
            raise AdapterError(
                "Platform Key is not scoped for MCP invocation",
                reason="scope_denied",
                status=403,
            )
        return identity

    async def decide(
        self,
        authorization: str,
        slug: str,
        capability_name: str,
    ) -> dict[str, Any]:
        response = await self.http.post(
            f"{API_BASE}/v1/mcp/decide",
            headers={"Authorization": authorization},
            json={"server_slug": slug, "capability_name": capability_name},
        )
        if response.status_code == 401:
            raise AdapterError("Invalid Platform Key", reason="invalid_platform_key", status=401)
        if response.status_code == 403:
            raise AdapterError(
                "Platform Key is not scoped for MCP invocation",
                reason="scope_denied",
                status=403,
            )
        if not response.is_success:
            raise AdapterError(
                "MCP policy service is unavailable",
                reason="policy_unavailable",
            )
        return response.json()

    async def record_usage(
        self,
        decision: dict[str, Any],
        capability_name: str,
        *,
        denied: bool,
        approval: bool,
        error: bool,
        latency_ms: float,
    ) -> None:
        server_id = decision.get("server_id")
        if not server_id:
            return
        key = (
            datetime.now(UTC).date().isoformat(),
            str(server_id),
            capability_name,
            str(decision["agent_id"]) if decision.get("agent_id") else None,
            str(decision["member_id"]) if decision.get("member_id") else None,
        )
        async with self.usage_lock:
            counter = self.usage.setdefault(key, UsageCounter())
            counter.add(
                denied=denied,
                approval=approval,
                error=error,
                latency_ms=latency_ms,
            )

    async def flush_usage(self) -> None:
        if not self.usage_bearer:
            return
        async with self.usage_lock:
            pending = self.usage
            self.usage = {}
        if not pending:
            return
        rows = [
            {
                "usage_date": day,
                "server_id": server_id,
                "capability_name": capability_name,
                "agent_id": agent_id,
                "member_id": member_id,
                "call_count": counter.call_count,
                "denied_count": counter.denied_count,
                "approval_count": counter.approval_count,
                "error_count": counter.error_count,
                "p95_latency_ms": counter.p95(),
                "cost_micros": 0,
            }
            for (day, server_id, capability_name, agent_id, member_id), counter in pending.items()
        ]
        authorization = self.usage_bearer
        if not authorization.lower().startswith("bearer "):
            authorization = f"Bearer {authorization}"
        try:
            response = await self.http.post(
                f"{API_BASE}/v1/mcp/usage",
                headers={"Authorization": authorization},
                json=rows,
            )
            response.raise_for_status()
        except Exception:
            log.exception("MCP usage flush failed; retaining aggregate counters")
            async with self.usage_lock:
                for key, counter in pending.items():
                    self.usage.setdefault(key, UsageCounter()).merge(counter)

    async def _usage_loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            await self.flush_usage()


runtime: Runtime


@asynccontextmanager
async def lifespan(_: FastAPI):
    global runtime
    runtime = Runtime()
    yield
    await runtime.close()


app = FastAPI(title="Agent Assurance MCP Adapter", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "deployed_servers": sorted(runtime.processes),
    }


@app.post("/v1/mcp/{server_slug}")
async def mediate(server_slug: str, request: Request) -> Response:
    started = time.perf_counter()
    tracer = getattr(runtime, "tracer", trace.get_tracer("agent-assurance.mcp"))
    span = tracer.start_span(
        "mcp.request",
        context=extract(dict(request.headers)),
        kind=SpanKind.SERVER,
    )
    authorization = request.headers.get("authorization", "")
    request_id: object = None
    rpc_method = "unknown"
    tool_name: str | None = None
    reason = "granted"
    outcome = "error"
    response_status = 500
    decision: dict[str, Any] | None = None
    principal: dict[str, Any] | None = None

    try:
        if not authorization.lower().startswith("bearer "):
            raise AdapterError(
                "AAP Platform Key required",
                reason="missing_platform_key",
                status=401,
            )
        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            raise AdapterError(
                "MCP request is too large",
                reason="request_too_large",
                status=413,
            )
        try:
            message = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                "Invalid JSON-RPC request",
                reason="invalid_json",
                status=400,
            ) from exc
        if not isinstance(message, dict):
            raise AdapterError(
                "JSON-RPC request must be an object",
                reason="invalid_json",
                status=400,
            )

        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            raise AdapterError(
                "JSON-RPC method is required",
                reason="invalid_method",
                status=400,
            )
        rpc_method = method

        if method == "tools/call":
            params = message.get("params")
            tool_name = params.get("name") if isinstance(params, dict) else None
            if not isinstance(tool_name, str) or not tool_name:
                raise AdapterError(
                    "Tool name is required",
                    reason="invalid_tool_call",
                    status=400,
                )
            decision = await runtime.decide(authorization, server_slug, tool_name)
            reason = str(decision.get("reason_code") or "policy_denied")
            if not decision.get("allowed"):
                raise AdapterError(
                    "Tool call blocked by Agent Assurance policy",
                    reason=reason,
                    status=403,
                )
            if decision.get("requires_approval"):
                raise AdapterError(
                    "Tool call requires human approval",
                    reason="approval_required",
                    status=403,
                )
            secret_kinds = _secret_kinds(body)
            if secret_kinds:
                reason = "secret_detected"
                raise AdapterError(
                    "Tool call blocked by data protection policy",
                    reason=reason,
                    status=403,
                )
        elif method == "tools/list":
            principal = await runtime.authenticate(authorization)
        elif method in {"initialize", "ping", "notifications/initialized", "notifications/cancelled"}:
            principal = await runtime.authenticate(authorization)
        else:
            principal = await runtime.authenticate(authorization)
            raise AdapterError(
                "This MCP method is not mediated",
                reason="method_not_supported",
                status=403,
            )

        upstream = await runtime.process_for(server_slug).exchange(message)
        if upstream is None:
            outcome = "accepted"
            response_status = 202
            return Response(status_code=202)

        if method == "tools/list":
            upstream = await _filter_tool_list(upstream, authorization, server_slug)

        outcome = "upstream_error" if "error" in upstream else "allowed"
        response_status = 200
        return JSONResponse(upstream)
    except AdapterError as exc:
        reason = exc.reason
        response_status = exc.status
        return JSONResponse(
            _jsonrpc_error(request_id, exc.reason, str(exc)),
            status_code=exc.status,
        )
    finally:
        _audit(
            slug=server_slug,
            method=rpc_method,
            tool=tool_name,
            outcome=outcome if reason == "granted" else "denied",
            reason=reason,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        if decision is not None and tool_name is not None:
            elapsed_ms = (time.perf_counter() - started) * 1000
            await runtime.record_usage(
                decision,
                tool_name,
                denied=response_status in {401, 403},
                approval=reason == "approval_required",
                error=response_status >= 500 or outcome == "upstream_error",
                latency_ms=elapsed_ms,
            )
        _finish_span(
            span,
            server_slug=server_slug,
            rpc_method=rpc_method,
            tool_name=tool_name,
            reason=reason,
            outcome=outcome,
            response_status=response_status,
            latency_ms=(time.perf_counter() - started) * 1000,
            identity=decision or principal,
        )


async def _filter_tool_list(
    response: dict[str, Any],
    authorization: str,
    server_slug: str,
) -> dict[str, Any]:
    result = response.get("result")
    if not isinstance(result, dict):
        return response
    tools = result.get("tools")
    if not isinstance(tools, list):
        return response

    async def permitted(tool: object) -> bool:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            return False
        decision = await runtime.decide(authorization, server_slug, tool["name"])
        return bool(decision.get("allowed"))

    decisions = await asyncio.gather(*(permitted(tool) for tool in tools))
    filtered = [tool for tool, allowed in zip(tools, decisions, strict=True) if allowed]
    return {**response, "result": {**result, "tools": filtered}}


def _finish_span(
    span: Any,
    *,
    server_slug: str,
    rpc_method: str,
    tool_name: str | None,
    reason: str,
    outcome: str,
    response_status: int,
    latency_ms: float,
    identity: dict[str, Any] | None,
) -> None:
    recorded_outcome = "denied" if response_status in {401, 403} else outcome
    span.update_name(f"mcp.{rpc_method}")
    attributes: dict[str, str | int | float] = {
        "rpc.system": "jsonrpc",
        "rpc.method": rpc_method,
        "http.response.status_code": response_status,
        "aap.mcp.server": server_slug,
        "aap.mcp.method": rpc_method,
        "aap.invocation.source": "mcp_adapter",
        "aap.sdk.name": "aap-mcp-adapter",
        "aap.policy.reason_code": reason,
        "aap.event.status": recorded_outcome,
        "aap.adapter.latency_ms": latency_ms,
    }
    if tool_name:
        attributes.update(
            {
                "gen_ai.tool.type": "mcp",
                "gen_ai.tool.name": tool_name,
                "mcp.tool.name": tool_name,
            }
        )
    if identity:
        project_id = identity.get("project_id")
        agent_id = identity.get("agent_id")
        member_id = identity.get("member_id")
        credential_id = identity.get("workload_credential_id") or identity.get("credential_id")
        environment = identity.get("environment")
        if project_id:
            attributes["aap.project.id"] = str(project_id)
        if agent_id:
            attributes["gen_ai.agent.id"] = str(agent_id)
            attributes["aap.actor.id"] = str(agent_id)
            attributes["aap.actor.type"] = "agent"
        elif credential_id:
            attributes["aap.actor.id"] = str(credential_id)
            attributes["aap.actor.type"] = "workload"
        if member_id:
            attributes["aap.user.id"] = str(member_id)
        if credential_id:
            attributes["aap.workload.credential_id"] = str(credential_id)
        if environment:
            attributes["deployment.environment.name"] = str(environment)
    span.set_attributes(attributes)
    if response_status >= 400 or outcome == "upstream_error":
        span.set_status(Status(StatusCode.ERROR, reason))
    else:
        span.set_status(Status(StatusCode.OK))
    span.end()


def _secret_kinds(body: bytes) -> list[str]:
    candidates = [body]
    try:
        decoded = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    else:
        # Inspect what the upstream server receives after JSON unescaping as well as the
        # original bytes, otherwise ``sk-\u0070roj-...`` bypasses a raw-body scanner.
        candidates.append(
            json.dumps(decoded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    return [
        kind
        for kind, pattern in SECRET_PATTERNS
        if any(pattern.search(candidate) for candidate in candidates)
    ]


def _jsonrpc_error(request_id: object, reason: str, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32003,
            "message": message,
            "data": {"reason_code": reason},
        },
    }


def _audit(
    *,
    slug: str,
    method: str,
    tool: str | None,
    outcome: str,
    reason: str,
    latency_ms: float,
) -> None:
    record = {
        "event": "mcp_request",
        "server_slug": slug,
        "http_method": method,
        "capability_name": tool,
        "outcome": outcome,
        "reason_code": reason,
        "latency_ms": round(latency_ms, 3),
    }
    log.info(json.dumps(record, separators=(",", ":"), sort_keys=True))
