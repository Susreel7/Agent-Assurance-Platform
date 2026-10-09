import { useMemo, useState } from "react";
import type { ExecutionSummary } from "@/api/types";
import { useObservePayloadRefs } from "@/api/suiteQueries";
import { Badge } from "@/components/StateBadge";
import { formatTableDate } from "@/lib/dates";
import {
  executionTypeLabel,
  formatDuration,
  type ExecutionGraphItem,
  type ExecutionVisualStatus,
} from "./executionGraphModel";
import { PayloadViewer } from "./PayloadViewer";

type Props = {
  projectId: string;
  traceId: string;
  execution: ExecutionSummary;
  item: ExecutionGraphItem | null;
};

const statusTone: Record<ExecutionVisualStatus, "ok" | "warn" | "risk" | "info" | "mute"> = {
  queued: "mute",
  running: "info",
  succeeded: "ok",
  failed: "risk",
  skipped: "mute",
  retry: "warn",
  waiting: "warn",
  unknown: "mute",
};

function Field({ label, value }: { label: string; value?: string | number | null }) {
  if (value == null || value === "") return null;
  return (
    <div className="grid grid-cols-[84px_minmax(0,1fr)] gap-2 border-b border-line-200 py-2 text-xs last:border-b-0">
      <dt className="text-ink-400">{label}</dt>
      <dd className="min-w-0 break-words text-ink-700">{value}</dd>
    </div>
  );
}

function typeTab(type: string): { id: string; label: string } | null {
  if (type === "generation") return { id: "operation", label: "Model" };
  if (type === "tool") return { id: "operation", label: "Tool" };
  if (type === "retrieval") return { id: "operation", label: "Retrieval" };
  if (type === "http") return { id: "operation", label: "HTTP" };
  if (type === "database") return { id: "operation", label: "Database" };
  if (type === "mcp") return { id: "operation", label: "MCP" };
  if (type === "a2a") return { id: "operation", label: "Agent link" };
  if (type === "sdk") return { id: "operation", label: "SDK" };
  if (type === "node") return { id: "operation", label: "Node" };
  if (type === "state_transition") return { id: "operation", label: "Transition" };
  if (type === "agent" || type === "chain") return { id: "operation", label: "Execution" };
  if (type === "evaluation") return { id: "operation", label: "Evaluation" };
  if (type === "human_approval") return { id: "operation", label: "Approval" };
  if (type === "retry") return { id: "operation", label: "Retry" };
  if (type === "error") return { id: "operation", label: "Error" };
  if (type === "event") return { id: "operation", label: "Event" };
  return null;
}

function contentTabLabel(type: string): string {
  if (type === "generation") return "Prompt & response";
  if (["tool", "sdk", "mcp", "http", "database", "retrieval"].includes(type)) {
    return "Arguments & result";
  }
  if (type === "node" || type === "state_transition") return "State";
  return "Input & output";
}

export function ExecutionInspector({ projectId, traceId, execution, item }: Props) {
  const payloadQuery = useObservePayloadRefs(
    projectId,
    traceId,
    Boolean(item?.observation),
  );
  const [activeTab, setActiveTab] = useState("overview");

  const payloads = useMemo(
    () =>
      (payloadQuery.data ?? []).filter(
        (reference) => reference.span_id === item?.observation?.span_id,
      ),
    [item?.observation?.span_id, payloadQuery.data],
  );
  const tabs = useMemo(() => {
    if (!item) return [];
    const output = [{ id: "overview", label: "Overview" }];
    const operationTab = typeTab(item.type);
    if (operationTab) output.push(operationTab);
    if (item.observation) {
      output.push({ id: "content", label: contentTabLabel(item.type) });
    }
    output.push({ id: "metadata", label: "Metadata" });
    return output;
  }, [item]);

  if (!item) {
    return (
      <div className="p-4 text-xs leading-5 text-ink-400">
        Select an operation in the graph or tree. The URL will retain the selected span so
        this exact context can be shared.
      </div>
    );
  }

  const observation = item.observation;
  const event = item.event;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="shrink-0 border-b border-line-200 p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink-900">{item.label}</p>
            <p className="mt-0.5 text-micro uppercase tracking-wide text-ink-400">
              {executionTypeLabel(item.type)}
            </p>
          </div>
          <Badge label={executionTypeLabel(item.status)} tone={statusTone[item.status]} />
        </div>
      </div>

      <div className="flex shrink-0 overflow-x-auto border-b border-line-200 bg-bg-sunk" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`shrink-0 border-b-2 px-2.5 py-2 text-micro font-medium ${
              activeTab === tab.id
                ? "border-info-fg text-info-fg"
                : "border-transparent text-ink-400 hover:text-ink-700"
            }`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {activeTab === "overview" ? (
          <dl className="px-3">
            <Field label="Status" value={executionTypeLabel(item.status)} />
            <Field label="Duration" value={formatDuration(item.durationMs)} />
            <Field label="Started" value={item.startTime ? formatTableDate(item.startTime) : null} />
            <Field label="Parent" value={item.parentId} />
            <Field label="Actor" value={observation?.effective_actor_id ?? event?.effective_actor_id} />
            <Field label="Agent" value={observation?.agent_name ?? execution.agent_name} />
            <Field label="Session" value={observation?.session_id ?? execution.session_id} />
            <Field label="Source" value={item.source} />
          </dl>
        ) : null}

        {activeTab === "operation" && observation ? (
          <dl className="px-3">
            <Field label="Operation" value={observation.operation_name} />
            <Field label="Status" value={observation.outcome} />
            <Field label="Duration" value={formatDuration(observation.duration_ms)} />
            {item.type === "generation" ? (
              <>
                <Field label="Provider" value={observation.provider} />
                <Field label="Model" value={observation.model} />
                <Field label="Input tokens" value={observation.input_tokens} />
                <Field label="Output tokens" value={observation.output_tokens} />
                <Field
                  label="Cost"
                  value={
                    observation.cost_micros > 0
                      ? `$${(observation.cost_micros / 1_000_000).toFixed(4)}`
                      : null
                  }
                />
              </>
            ) : null}
            {item.type === "sdk" ? (
              <>
                <Field label="SDK" value={observation.sdk_name} />
                <Field label="Version" value={observation.sdk_version} />
                <Field label="Operation" value={observation.sdk_operation} />
              </>
            ) : null}
            {["tool", "retrieval", "http", "database"].includes(item.type) ? (
              <>
                <Field label="Tool" value={observation.tool_name ?? observation.operation_name} />
                <Field label="MCP server" value={observation.mcp_server} />
                <Field label="MCP method" value={observation.mcp_method} />
                <Field label="Service" value={observation.service_name} />
              </>
            ) : null}
            {item.type === "mcp" ? (
              <>
                <Field label="MCP server" value={observation.mcp_server} />
                <Field label="Method" value={observation.mcp_method} />
                <Field label="Role" value={observation.mcp_role} />
                <Field label="Request" value={observation.mcp_request_id} />
              </>
            ) : null}
            {item.type === "a2a" ? (
              <>
                <Field label="Target agent" value={observation.a2a_target_agent_id} />
                <Field
                  label="Target execution"
                  value={observation.a2a_target_execution_id}
                />
                <Field label="Target trace" value={observation.a2a_target_trace_id} />
              </>
            ) : null}
            {["node", "state_transition"].includes(item.type) ? (
              <>
                <Field label="Graph node" value={observation.graph_node_id} />
                <Field label="Node path" value={observation.graph_node_path} />
                <Field label="Span kind" value={observation.kind} />
                <Field label="Retry" value={observation.retry_attempt || null} />
              </>
            ) : null}
            {["agent", "chain", "evaluation"].includes(item.type) ? (
              <>
                <Field label="Execution" value={execution.execution_id} />
                <Field label="Version" value={execution.agent_version_id} />
                <Field label="Framework" value={execution.framework} />
                <Field label="Nodes" value={execution.node_count} />
                <Field label="Models" value={execution.generation_count} />
                <Field label="Tools" value={execution.tool_count} />
                <Field label="SDK calls" value={execution.sdk_count} />
              </>
            ) : null}
            {["retry", "error", "human_approval", "event"].includes(item.type) ? (
              <>
                <Field label="Attempt" value={observation.retry_attempt || null} />
                <Field label="Service" value={observation.service_name} />
              </>
            ) : null}
          </dl>
        ) : null}

        {activeTab === "operation" && event ? (
          <dl className="px-3">
            <Field label="Event" value={event.event_type} />
            <Field label="Status" value={event.status} />
            <Field label="Sequence" value={event.sequence} />
            <Field label="Tool" value={event.tool_name} />
            <Field label="Model" value={event.model} />
            <Field label="SDK" value={event.sdk_name} />
            <Field label="SDK operation" value={event.sdk_operation} />
            <Field label="MCP server" value={event.mcp_server} />
            <Field label="MCP method" value={event.mcp_method} />
          </dl>
        ) : null}

        {activeTab === "content" ? (
          <div className="space-y-3 p-3">
            {payloadQuery.isLoading ? (
              <p className="text-xs text-ink-400">Loading payload metadata…</p>
            ) : payloadQuery.isError ? (
              <div className="text-xs text-risk-fg">
                Payload metadata is unavailable.{" "}
                <button type="button" onClick={() => void payloadQuery.refetch()} className="underline">
                  Retry
                </button>
              </div>
            ) : payloads.length > 0 ? (
              payloads.map((reference) => (
                <PayloadViewer
                  key={`${reference.payload_id}:${reference.field_name}`}
                  projectId={projectId}
                  reference={reference}
                />
              ))
            ) : (
              <div className="border border-line-200 bg-bg-sunk p-3 text-xs leading-5 text-ink-400">
                No retained content is available for this operation. The capture policy may be
                metadata-only, or the operation did not emit input/output fields.
              </div>
            )}
          </div>
        ) : null}

        {activeTab === "metadata" ? (
          <dl className="px-3">
            <Field label="Span ID" value={observation?.span_id ?? event?.span_id} />
            <Field label="Event ID" value={event?.event_uid} />
            <Field label="Trace ID" value={event?.trace_id ?? execution.trace_id} />
            <Field label="Execution ID" value={observation?.execution_id ?? event?.execution_id} />
            <Field label="Type" value={observation?.observation_type ?? event?.observation_type} />
            <Field label="Kind" value={observation?.kind} />
            <Field label="Service" value={observation?.service_name} />
            <Field label="Environment" value={observation?.environment_id} />
            <Field label="Agent ID" value={observation?.agent_id ?? execution.agent_id} />
            <Field label="Version ID" value={observation?.agent_version_id} />
            <Field label="User session" value={observation?.user_session_id} />
            <Field label="Sequence" value={event?.sequence} />
            <Field label="Tags" value={observation?.tags?.join(", ")} />
            {event
              ? Object.entries(event.attributes ?? {}).map(([key, value]) => (
                  <Field key={key} label={key} value={value} />
                ))
              : null}
          </dl>
        ) : null}
      </div>
    </div>
  );
}
