import { describe, expect, it } from "vitest";
import { trace } from "@opentelemetry/api";
import { InMemorySpanExporter } from "@opentelemetry/sdk-trace-base";

import { configure, shutdown } from "../src/client.js";
import {
  currentSpanIdentity,
  extractHeaders,
  extractMcpContext,
  injectHeaders,
  injectMcpContext,
} from "../src/context.js";
import {
  a2aSpan,
  agentSpan,
  mcpSpan,
  nodeSpan,
  recordEvent,
  toolSpan,
  withSpan,
} from "../src/spans.js";
import { installTestTracerProvider } from "./testHarness.js";

describe("spans", () => {
  it("nests parent/child spans", async () => {
    const exporter = new InMemorySpanExporter();
    installTestTracerProvider(exporter);
    configure({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
    });

    await withSpan("root", { "gen_ai.operation.name": "workflow" }, async () => {
      const parent = currentSpanIdentity();
      await toolSpan("search", { q: "a" })(async () => {
        const child = currentSpanIdentity();
        expect(child?.traceId).toBe(parent?.traceId);
        expect(child?.spanId).not.toBe(parent?.spanId);
      });
    });
    await agentSpan("foss-remediation")(async () => {
      await nodeSpan("analysis", { repository: "acme/payments" })(async () => {
        recordEvent("state.transition", {
          "aap.observation.type": "state_transition",
          "aap.state.to": "analysis",
        });
      });
    });

    const spans = exporter.getFinishedSpans();
    const agent = spans.find((span) => span.attributes["aap.observation.type"] === "agent");
    const node = spans.find((span) => span.attributes["aap.observation.type"] === "node");
    expect(agent).toBeDefined();
    expect(node?.attributes["aap.execution.id"]).toBe(agent?.attributes["aap.execution.id"]);
    expect(node?.events[0]?.name).toBe("state.transition");

    await shutdown();
    exporter.reset();
  });

  it("w3c inject/extract", async () => {
    installTestTracerProvider(new InMemorySpanExporter());
    configure({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
    });
    const carrier: Record<string, string> = {};
    await withSpan("http", {}, async () => {
      injectHeaders(carrier);
    });
    expect(carrier.traceparent).toBeDefined();
    extractHeaders(carrier);
    await shutdown();
  });

  it("propagates MCP context and emits typed MCP/A2A spans", async () => {
    const exporter = new InMemorySpanExporter();
    installTestTracerProvider(exporter);
    configure({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
    });
    const message: Record<string, unknown> = { jsonrpc: "2.0", id: "request-1" };
    let expectedSpanId = "";
    await withSpan("mcp-envelope", {}, async () => {
      expectedSpanId = currentSpanIdentity()?.spanId ?? "";
      injectMcpContext(message);
    });
    expect(trace.getSpan(extractMcpContext(message))?.spanContext().spanId).toBe(expectedSpanId);
    await mcpSpan("github", "tools/call", {
      role: "client",
      requestId: "mcp-1",
      arguments: { authorization: "must-not-be-stored" },
    })(async () => {});
    await a2aSpan("coding-agent", {
      targetExecutionId: "exec-child",
      targetTraceId: "f".repeat(32),
    })(async () => {});
    const mcp = exporter
      .getFinishedSpans()
      .find((span) => span.attributes["aap.observation.type"] === "mcp");
    const a2a = exporter
      .getFinishedSpans()
      .find((span) => span.attributes["aap.observation.type"] === "a2a");
    expect(mcp?.attributes["aap.mcp.request_id"]).toBe("mcp-1");
    expect(String(mcp?.attributes)).not.toContain("must-not-be-stored");
    expect(a2a?.attributes["aap.a2a.target_execution_id"]).toBe("exec-child");
    await shutdown();
  });

  it("propagates exceptions from withSpan", async () => {
    installTestTracerProvider(new InMemorySpanExporter());
    configure({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
    });
    await expect(
      withSpan("fail", {}, async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    await shutdown();
  });
});
