import { describe, expect, it } from "vitest";

import { TraceClient } from "../src/client.js";

describe("client", () => {
  it("no-op when disabled", async () => {
    const client = new TraceClient({
      endpoint: "",
      bearerToken: "",
      organizationId: "o",
      projectId: "p",
      enabled: false,
    });
    expect(await client.flush()).toBe(true);
    await client.shutdown();
  });

  it("normalizes endpoint for OTLP", async () => {
    const client = new TraceClient({
      endpoint: "https://observe.example",
      bearerToken: "aap_wk_org.1.secret",
      organizationId: "o",
      projectId: "p",
      enabled: true,
    });
    expect(client.config.endpoint).toBe("https://observe.example");
    await client.shutdown();
  });

  it("rejects an invalid sample rate", () => {
    expect(
      () =>
        new TraceClient({
          endpoint: "",
          bearerToken: "",
          organizationId: "o",
          projectId: "p",
          enabled: false,
          sampleRate: 1.1,
        }),
    ).toThrow(/sampleRate/);
  });
});
