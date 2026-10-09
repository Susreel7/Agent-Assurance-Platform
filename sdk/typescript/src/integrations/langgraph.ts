import {
  agentSpan,
  nodeSpan,
  recordEvent,
  recordOutputState,
} from "../spans.js";

export function wrapLangGraphNode<TArgs extends unknown[], TResult>(
  nodeName: string,
  fn: (...args: TArgs) => Promise<TResult> | TResult,
  options: {
    graphName?: string;
    graphVersion?: string;
    nodePath?: string;
  } = {},
): (...args: TArgs) => Promise<TResult> {
  return async (...args: TArgs) =>
    nodeSpan(
      nodeName,
      args[0],
      {
        "aap.graph.name": options.graphName,
        "aap.graph.version": options.graphVersion,
        "aap.graph.node.path": options.nodePath ?? nodeName,
      },
    )(async (span) => {
      const result = await fn(...args);
      recordOutputState(span, result);
      return result;
    });
}

export interface LangGraphLike<TInput, TOutput> {
  invoke(input: TInput, config?: Record<string, unknown>): Promise<TOutput>;
  stream?(
    input: TInput,
    config?: Record<string, unknown>,
  ): Promise<AsyncIterable<unknown>> | AsyncIterable<unknown>;
  getGraph?(): unknown;
}

function hasInterrupt(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some(hasInterrupt);
  if ("__interrupt__" in value) return true;
  return Object.values(value).some(hasInterrupt);
}

export function instrumentLangGraph<TInput, TOutput>(
  graph: LangGraphLike<TInput, TOutput>,
  options: {
    graphName: string;
    graphVersion?: string;
    agentName?: string;
  },
): LangGraphLike<TInput, TOutput> {
  return new Proxy(graph, {
    get(target, property, receiver) {
      if (property === "invoke") {
        return async (input: TInput, config?: Record<string, unknown>) =>
          agentSpan(options.agentName ?? options.graphName, {
            "aap.graph.name": options.graphName,
            "aap.graph.version": options.graphVersion,
            "aap.framework.name": "langgraph",
          })(async () => {
            const result = await target.invoke(input, config);
            if (hasInterrupt(result)) {
              recordEvent("execution.interrupted", {
                "aap.observation.type": "human_approval",
              });
            }
            return result;
          });
      }
      return Reflect.get(target, property, receiver);
    },
  });
}
