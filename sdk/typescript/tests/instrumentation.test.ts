import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SpanStatusCode } from "@opentelemetry/api";
import { InMemorySpanExporter } from "@opentelemetry/sdk-trace-base";

import { configure, shutdown } from "../src/client.js";
import { createLangChainCallbacks } from "../src/integrations/langchain.js";
import { wrapAnthropicMessagesCreate } from "../src/integrations/anthropic.js";
import { wrapOpenAIChatCreate } from "../src/integrations/openai.js";
import { stripHiddenReasoning } from "../src/generation.js";
import { safeHttpUrl } from "../src/safeHttp.js";
import {
  cursorSdkOperation,
  databaseSpan,
  httpSpan,
  observeDatabaseCall,
  observeHttpCall,
  observationSpan,
  retrievalSpan,
  withSpan,
} from "../src/spans.js";
import { installTestTracerProvider } from "./testHarness.js";

describe("instrumentation phase 4", () => {
  let exporter: InMemorySpanExporter;

  beforeEach(() => {
    exporter = new InMemorySpanExporter();
    installTestTracerProvider(exporter);
    configure({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
    });
  });

  afterEach(async () => {
    await shutdown();
    exporter.reset();
  });

  it("strips hidden reasoning from capture payloads", () => {
    const input = {
      role: "assistant",
      content: [
        { type: "text", text: "hello" },
        { type: "thinking", text: "secret" },
      ],
      reasoning: "hidden",
    };
    const out = stripHiddenReasoning(input) as {
      content: unknown[];
      reasoning?: string;
    };
    expect(out.reasoning).toBeUndefined();
    expect(out.content).toHaveLength(1);
  });

  it("safe HTTP URL drops credentials and query", () => {
    const parts = safeHttpUrl("https://user:pass@api.example.com/v1/items?token=secret#frag");
    expect(parts?.host).toBe("api.example.com");
    expect(parts?.route).toBe("/v1/items");
    expect(JSON.stringify(parts)).not.toContain("secret");
    expect(JSON.stringify(parts)).not.toContain("pass");
  });

  it("http observation excludes query string from attributes", async () => {
    await httpSpan("GET", "https://api.example.com/search?q=secret")(async () => undefined);
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.attributes["http.route"]).toBe("/search");
    expect(JSON.stringify(span.attributes)).not.toContain("secret");
  });

  it("database span only captures statement under capture policy", async () => {
    configure({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
      captureMode: "none",
    });
    await databaseSpan("postgresql", "SELECT", "orders", "SELECT * FROM orders")(async () => undefined);
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.attributes["db.statement"]).toBeUndefined();
    expect(span.attributes["db.operation"]).toBe("SELECT");
  });

  it("observeDatabaseCall records duration without leaking statement when capture is off", async () => {
    configure({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
      captureMode: "none",
    });
    await observeDatabaseCall("postgresql", "SELECT", "orders", async () => ({ rows: 1 }), {
      statement: "SELECT password FROM users",
    });
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.attributes["db.statement"]).toBeUndefined();
    expect(span.attributes["db.client.operation.duration_ms"]).toBeDefined();
  });

  it("cursor SDK operation sets sdk attributes", async () => {
    configure({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
      captureMode: "digest",
    });
    await cursorSdkOperation("read_file", { path: "/src/a.ts" })(async () => undefined);
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.attributes["aap.sdk.name"]).toBe("cursor");
    expect(span.attributes["aap.sdk.operation"]).toBe("read_file");
    expect(span.attributes["aap.sdk.arguments.digest"]).toBeDefined();
  });

  it("generic observation span sets observation type", async () => {
    await observationSpan("guardrail", "input-policy", { "aap.guardrail.name": "pii" })(
      async () => undefined,
    );
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.attributes["aap.observation.type"]).toBe("guardrail");
  });

  it("LangChain callbacks keep spans open until end", async () => {
    const callbacks = createLangChainCallbacks();
    await callbacks.handleLLMStart("run-1", "gpt-test", ["hello"]);
    expect(exporter.getFinishedSpans()).toHaveLength(0);
    callbacks.handleLLMEnd("run-1", { generations: [[{ text: "world" }]] });
    expect(exporter.getFinishedSpans()).toHaveLength(1);
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.name).toBe("generation:gpt-test");
    expect(span.status.code).toBe(SpanStatusCode.OK);
  });

  it("OpenAI stream span ends after consumption", async () => {
    const wrapped = wrapOpenAIChatCreate(async () => {
      async function* stream() {
        yield { id: "resp-1", choices: [{ delta: { content: "hi" } }] };
        yield {
          id: "resp-1",
          usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 },
          choices: [{ finish_reason: "stop", delta: {} }],
        };
      }
      return stream();
    });
    const stream = (await wrapped(null, { model: "gpt-test", stream: true })) as AsyncIterable<
      unknown
    >;
    expect(exporter.getFinishedSpans()).toHaveLength(0);
    for await (const chunk of stream) {
      void chunk;
    }
    expect(exporter.getFinishedSpans()).toHaveLength(1);
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.attributes["gen_ai.response.id"]).toBe("resp-1");
    expect(span.attributes["gen_ai.usage.input_tokens"]).toBe(3);
    expect(span.attributes["gen_ai.response.streaming_chunks"]).toBe(2);
  });

  it("OpenAI stream span ends on consumer error with error status", async () => {
    const wrapped = wrapOpenAIChatCreate(async () => {
      async function* stream() {
        yield { id: "resp-2", choices: [{ delta: { content: "x" } }] };
        yield { id: "resp-2", choices: [{ delta: { content: "y" } }] };
      }
      return stream();
    });
    const stream = (await wrapped(null, { model: "gpt-test", stream: true })) as AsyncIterable<
      unknown
    >;
    await expect(async () => {
      for await (const chunk of stream) {
        if (chunk) {
          throw new Error("consumer stopped");
        }
      }
    }).rejects.toThrow("consumer stopped");
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.status.code).toBe(SpanStatusCode.ERROR);
    expect(span.attributes["gen_ai.response.streaming_chunks"]).toBe(1);
  });

  it("Anthropic stream span stays open until cancelled", async () => {
    const wrapped = wrapAnthropicMessagesCreate(async () => {
      async function* stream() {
        yield {
          type: "message_start",
          message: { id: "msg-1", model: "claude-test", usage: { input_tokens: 4 } },
        };
        yield { type: "content_block_delta", delta: { type: "text_delta", text: "hi" } };
        const err = new Error("cancelled");
        err.name = "AbortError";
        throw err;
      }
      return stream();
    });
    const stream = (await wrapped({ model: "claude-test", stream: true })) as AsyncIterable<
      unknown
    >;
    await expect(async () => {
      for await (const chunk of stream) {
        void chunk;
      }
    }).rejects.toThrow("cancelled");
    const span = exporter.getFinishedSpans()[0]!;
    expect(span.attributes["gen_ai.response.id"]).toBe("msg-1");
    expect(span.events.some((e) => e.name === "gen_ai.streaming.cancelled")).toBe(true);
    expect(span.status.code).toBe(SpanStatusCode.ERROR);
  });

  it("nests manual and automatic spans with shared trace", async () => {
    await withSpan("root", { "aap.observation.type": "workflow" }, async () => {
      await retrievalSpan("policy docs")(async () => undefined);
      await observeHttpCall("POST", "https://peer.example/v1/run", async () => ({ status: 200 }), {
        statusFromResult: (r) => r.status,
        peerService: "peer",
      });
    });
    const spans = exporter.getFinishedSpans();
    expect(spans.length).toBeGreaterThanOrEqual(3);
    const traceIds = new Set(spans.map((s) => s.spanContext().traceId));
    expect(traceIds.size).toBe(1);
  });
});
