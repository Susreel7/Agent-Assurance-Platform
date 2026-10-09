import { afterEach, describe, expect, it, vi } from "vitest";

import { ScoreClient } from "../src/scores.js";
import type { TraceConfig } from "../src/config.js";

describe("ScoreClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts evaluate workload score contract to scoreBaseUrl", async () => {
    const config: TraceConfig = {
      endpoint: "https://observe.example/v1/traces",
      bearerToken: "secret",
      organizationId: "o",
      projectId: "p",
      scoreBaseUrl: "https://control.example",
    };
    const fetchMock = vi.fn(async () => new Response(null, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    await new ScoreClient(config).submit({
      name: "quality",
      value: 0.9,
      traceId: "trace-1",
      comment: "ok",
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://control.example/v1/evaluate/workload/scores");
    expect(JSON.parse(String(init.body))).toEqual({
      target_type: "trace",
      target_id: "trace-1",
      name: "quality",
      value_type: "numeric",
      value_numeric: 0.9,
      source: "human",
      explanation: "ok",
    });
  });

  it("derives control base from trace endpoint when scoreBaseUrl is unset", async () => {
    const config: TraceConfig = {
      endpoint: "https://gateway.example/v1/traces",
      bearerToken: "secret",
      organizationId: "o",
      projectId: "p",
    };
    const fetchMock = vi.fn(async () => new Response(null, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    await new ScoreClient(config).submit({
      name: "n",
      value: 1,
      spanId: "span-1",
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("https://gateway.example/v1/evaluate/workload/scores");
  });
});
