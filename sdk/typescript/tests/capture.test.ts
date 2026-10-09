import { describe, expect, it } from "vitest";
import { applyCapture, digestValue, redactText } from "../src/capture.js";

describe("capture", () => {
  it("digest mode omits raw secret", () => {
    const out = applyCapture("digest", "gen_ai.input.messages", { content: "secret" });
    expect(out).not.toBeNull();
    expect(JSON.stringify(out)).not.toContain("secret");
  });

  it("redacted mode masks email", () => {
    const out = applyCapture("redacted", "gen_ai.input.messages", "mail user@test.com");
    expect(out?.["gen_ai.input.messages.preview"]).toContain("[email]");
  });

  it("full mode keeps digest", () => {
    const out = applyCapture("full", "gen_ai.input.messages", "hello");
    expect(out?.["gen_ai.input.messages"]).toBe("hello");
    expect(out?.["gen_ai.input.messages.digest"]).toBe(digestValue("hello"));
  });

  it("redact helper", () => {
    expect(redactText("x@y.com")).toContain("[email]");
  });
});
