import type { Context, Span } from "@opentelemetry/api";
import { context } from "@opentelemetry/api";

import { applyCapture } from "../capture.js";
import type { CaptureMode } from "../capture.js";
import { getClient } from "../client.js";
import { generationRequestAttributes, generationResponseAttributes } from "../generation.js";
import { startManualSpan, startToolSpan, type ManualSpanHandle } from "../spans.js";

/** Duck-typed LangChain callback hooks. */
export interface LangChainHandlers {
  handleLLMStart(runId: string, model: string, prompts: string[]): Promise<void>;
  handleLLMEnd(runId: string, response?: unknown): void;
  handleLLMError(runId: string, error: unknown): void;
  handleToolStart(runId: string, tool: string, input: string): Promise<void>;
  handleToolEnd(runId: string, output?: unknown): void;
  handleToolError(runId: string, error: unknown): void;
}

function captureMode(): CaptureMode {
  return getClient().config.captureMode ?? "none";
}

function applyToolResult(span: Span, output: unknown): void {
  const captured = applyCapture(captureMode(), "gen_ai.tool.call.result", output);
  if (captured) {
    for (const [key, value] of Object.entries(captured)) {
      if (value !== undefined && value !== null) {
        span.setAttribute(key, typeof value === "string" ? value : JSON.stringify(value));
      }
    }
  }
}

export function createLangChainCallbacks(): LangChainHandlers {
  const llmHandles = new Map<string, ManualSpanHandle>();
  const toolHandles = new Map<string, ManualSpanHandle>();
  const llmStack: string[] = [];

  const parentContext = (): Context => {
    for (let i = llmStack.length - 1; i >= 0; i -= 1) {
      const handle = llmHandles.get(llmStack[i]!);
      if (handle) {
        return handle.otelContext;
      }
    }
    return context.active();
  };

  return {
    async handleLLMStart(runId, model, prompts) {
      const attrs = generationRequestAttributes(
        { provider: "langchain", model, inputMessages: prompts },
        captureMode(),
      );
      const handle = startManualSpan(`generation:${model}`, attrs, parentContext());
      llmHandles.set(runId, handle);
      llmStack.push(runId);
    },
    handleLLMEnd(runId, response) {
      const handle = llmHandles.get(runId);
      if (!handle) {
        return;
      }
      llmHandles.delete(runId);
      const idx = llmStack.lastIndexOf(runId);
      if (idx >= 0) {
        llmStack.splice(idx, 1);
      }
      const text = extractLangChainLlmText(response);
      if (text !== undefined) {
        const captured = generationResponseAttributes({ outputMessages: text }, captureMode());
        for (const [key, value] of Object.entries(captured)) {
          if (value !== undefined && value !== null) {
            handle.span.setAttribute(
              key,
              typeof value === "string" || typeof value === "number" || typeof value === "boolean"
                ? value
                : JSON.stringify(value),
            );
          }
        }
      }
      handle.end();
    },
    handleLLMError(runId, error) {
      const handle = llmHandles.get(runId);
      if (!handle) {
        return;
      }
      llmHandles.delete(runId);
      const idx = llmStack.lastIndexOf(runId);
      if (idx >= 0) {
        llmStack.splice(idx, 1);
      }
      handle.end(error);
    },
    async handleToolStart(runId, tool, input) {
      toolHandles.set(runId, startToolSpan(tool, input, {}, parentContext()));
    },
    handleToolEnd(runId, output) {
      const handle = toolHandles.get(runId);
      if (!handle) {
        return;
      }
      toolHandles.delete(runId);
      applyToolResult(handle.span, output);
      handle.end();
    },
    handleToolError(runId, error) {
      const handle = toolHandles.get(runId);
      if (!handle) {
        return;
      }
      toolHandles.delete(runId);
      handle.end(error);
    },
  };
}

function extractLangChainLlmText(response: unknown): string | undefined {
  if (response == null || typeof response !== "object") {
    return undefined;
  }
  const generations = (response as { generations?: unknown }).generations;
  if (!Array.isArray(generations) || !Array.isArray(generations[0])) {
    return undefined;
  }
  const first = generations[0][0] as { text?: string } | undefined;
  return typeof first?.text === "string" ? first.text : undefined;
}
