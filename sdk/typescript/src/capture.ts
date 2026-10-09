import { createHash } from "node:crypto";

export type CaptureMode = "none" | "digest" | "redacted" | "full";

export function digestValue(value: unknown): string {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? null);
  return "sha256:" + createHash("sha256").update(text).digest("hex");
}

const EMAIL = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;

export function redactText(text: string, maxPreview = 256): string {
  let out = text.replace(EMAIL, "[email]");
  if (out.length > maxPreview) {
    out = out.slice(0, maxPreview - 3) + "...";
  }
  return out;
}

export function applyCapture(
  mode: CaptureMode,
  field: string,
  value: unknown,
): Record<string, string | unknown> | null {
  if (value == null || mode === "none") return null;
  if (mode === "digest") {
    return { [`${field}.digest`]: digestValue(value) };
  }
  if (mode === "redacted") {
    return {
      [`${field}.digest`]: digestValue(value),
      [`${field}.preview`]: redactText(String(value)),
    };
  }
  if (mode === "full") {
    return { [field]: value, [`${field}.digest`]: digestValue(value) };
  }
  return null;
}
