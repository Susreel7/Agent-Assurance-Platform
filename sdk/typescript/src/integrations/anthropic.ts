import type { CaptureMode } from "../capture.js";
import { getClient } from "../client.js";
import {
  anthropicRequestParameters,
  anthropicResponseDetails,
  anthropicStreamChunkDetails,
  generationRequestAttributes,
  mergeGenerationResponseDetails,
  type GenerationResponseDetails,
} from "../generation.js";
import { recordGenerationOutput, startManualSpan } from "../spans.js";
import { wrapAsyncGenerator } from "../streaming.js";

type MessagesCreate = (...args: unknown[]) => Promise<unknown>;

function captureMode(): CaptureMode {
  return getClient().config.captureMode ?? "none";
}

export function wrapAnthropicMessagesCreate(original: MessagesCreate): MessagesCreate {
  return async (...args: unknown[]) => {
    const kwargs = (args[0] as Record<string, unknown>) ?? {};
    const model = String(kwargs.model ?? "unknown");
    const stream = Boolean(kwargs.stream);
    const attrs = generationRequestAttributes(
      {
        provider: "anthropic",
        model,
        inputMessages: kwargs.messages,
        systemInstructions: kwargs.system,
        parameters: anthropicRequestParameters(kwargs),
      },
      captureMode(),
    );
    const handle = startManualSpan(`generation:${model}`, attrs);
    try {
        const result = await original(...args);
        if (stream && result && typeof result === "object" && Symbol.asyncIterator in result) {
          let accumulated: GenerationResponseDetails = {};
          let streamError: unknown;
          async function* gen() {
            let completed = false;
            try {
              for await (const chunk of wrapAsyncGenerator(
                handle.span,
                result as AsyncIterable<unknown>,
                {
                  onChunk(chunk) {
                    accumulated = mergeGenerationResponseDetails(
                      accumulated,
                      anthropicStreamChunkDetails(chunk),
                    );
                  },
                },
              )) {
                try {
                  yield chunk;
                } catch (err) {
                  streamError = err;
                  throw err;
                }
              }
              completed = true;
            } catch (err) {
              streamError ??= err;
              throw err;
            } finally {
              recordGenerationOutput(handle.span, accumulated);
              if (!completed && streamError === undefined) {
                handle.end(new Error("stream consumer abandoned"));
              } else {
                handle.end(streamError);
              }
            }
          }
          return gen();
        }
        recordGenerationOutput(handle.span, anthropicResponseDetails(result));
        handle.end();
        return result;
    } catch (err) {
      handle.end(err);
      throw err;
    }
  };
}
