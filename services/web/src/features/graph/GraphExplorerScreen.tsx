import { useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { EMPTY_ITEMS, useBlastRadius, useGraphEdges, useGraphNodes } from "@/api/queries";
import type { GraphEdgeKind } from "@/api/types";
import { ErrorState } from "@/components/ErrorState";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { Toolbar } from "@/components/Toolbar";
import { titleCaseSnake } from "@/lib/formatters";
import { GraphCanvas } from "./GraphCanvas";
import {
  computeDeclaredObservedGaps,
  computeNeighbourhood,
  filterEdgesByKind,
} from "./graphUtils";

export default function GraphExplorerScreen() {
  const nodesQuery = useGraphNodes({ limit: "500", offset: "0" });
  const edgesQuery = useGraphEdges({ limit: "500", offset: "0" });

  const allNodes = nodesQuery.data?.items ?? EMPTY_ITEMS;
  const allEdges = edgesQuery.data?.items ?? EMPTY_ITEMS;

  const sortedNodes = useMemo(
    () => [...allNodes].sort((a, b) => a.label.localeCompare(b.label)),
    [allNodes],
  );

  const [focusNodeId, setFocusNodeId] = useState<string>("");
  const [depth, setDepth] = useState(2);
  const [edgeFilter, setEdgeFilter] = useState<GraphEdgeKind | "all">("all");
  const [blastMode, setBlastMode] = useState(false);
  const [blastOriginId, setBlastOriginId] = useState("");

  const effectiveFocus =
    focusNodeId || (sortedNodes[0]?.id ?? "");

  const filteredAllEdges = useMemo(
    () => filterEdgesByKind(allEdges, edgeFilter),
    [allEdges, edgeFilter],
  );

  const neighbourhood = useMemo(() => {
    if (!effectiveFocus) return { nodeIds: new Set<string>(), edgeIds: new Set<string>() };
    return computeNeighbourhood(effectiveFocus, depth, filteredAllEdges);
  }, [effectiveFocus, depth, filteredAllEdges]);

  const visibleNodes = useMemo(
    () => allNodes.filter((n) => neighbourhood.nodeIds.has(n.id)),
    [allNodes, neighbourhood.nodeIds],
  );

  const visibleEdges = useMemo(
    () => filteredAllEdges.filter((e) => neighbourhood.edgeIds.has(e.id)),
    [filteredAllEdges, neighbourhood.edgeIds],
  );

  const gapsInView = useMemo(() => {
    const gaps = computeDeclaredObservedGaps(allEdges);
    return gaps.filter(
      (g) =>
        neighbourhood.nodeIds.has(g.source_id) &&
        neighbourhood.nodeIds.has(g.target_id),
    );
  }, [allEdges, neighbourhood.nodeIds]);

  const gapEdgeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const g of gapsInView) {
      ids.add(g.declared_edge_id);
    }
    return ids;
  }, [gapsInView]);

  const declaredCount = visibleEdges.filter((e) => e.kind === "declared").length;
  const observedCount = visibleEdges.filter((e) => e.kind === "observed").length;

  const blastQuery = useBlastRadius(blastOriginId, blastMode && Boolean(blastOriginId));

  // The API answers "which nodes are reachable", not "which edges were traversed". It
  // used to be read as though it returned both; `edge_ids` was never a field, so the
  // edge highlight silently did nothing. An edge is in the blast radius when both of its
  // ends are, which is derivable here and does not need the server to say it.
  const highlightNodeIds = useMemo(() => {
    if (!blastMode || !blastQuery.data) return new Set<string>();
    return new Set((blastQuery.data.nodes ?? []).map((n) => n.node_id));
  }, [blastMode, blastQuery.data]);

  const highlightEdgeIds = useMemo(() => {
    if (highlightNodeIds.size === 0) return new Set<string>();
    return new Set(
      visibleEdges
        .filter((e) => highlightNodeIds.has(e.source_id) && highlightNodeIds.has(e.target_id))
        .map((e) => e.id),
    );
  }, [highlightNodeIds, visibleEdges]);

  // The blast radius response carries its own labels, so the id-to-node index that used
  // to resolve them here has no remaining reader.

  const loading = nodesQuery.isLoading || edgesQuery.isLoading;
  const error =
    nodesQuery.isError || edgesQuery.isError
      ? nodesQuery.error instanceof Error
        ? nodesQuery.error.message
        : edgesQuery.error instanceof Error
          ? edgesQuery.error.message
          : "Failed to load graph"
      : null;

  function handleNodeSelect(id: string) {
    if (blastMode) {
      setBlastOriginId(id);
    } else {
      setFocusNodeId(id);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton height="1.5rem" width="10rem" />
        <Skeleton height="3rem" />
        <Skeleton height="24rem" />
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState
        message={error}
        onRetry={() => {
          void nodesQuery.refetch();
          void edgesQuery.refetch();
        }}
      />
    );
  }

  if (allNodes.length === 0) {
    return (
      <Panel title="Graph explorer">
        <p className="text-table text-ink-600">No graph nodes in this estate.</p>
      </Panel>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Dependencies"
        explain="What your agents connect to — models, tools, data stores, each other. Highlighted links are ones you declared but have never actually been seen running, or the reverse."
      />

      <Panel noPadding title="Controls">
        <div className="space-y-3 p-4">
          <Toolbar>
            <label className="flex items-center gap-2 text-table text-ink-600">
              <span>Focus node</span>
              <select
                className="rounded-sm border border-line-200 bg-bg-panel px-2 py-1 text-ink-900"
                value={effectiveFocus}
                onChange={(e) => setFocusNodeId(e.target.value)}
                aria-label="Focus node"
              >
                {sortedNodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label} ({titleCaseSnake(n.kind)})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-table text-ink-600">
              <span>Depth</span>
              <select
                className="rounded-sm border border-line-200 bg-bg-panel px-2 py-1 tabular-nums"
                value={depth}
                onChange={(e) => setDepth(Number(e.target.value))}
                aria-label="Neighbourhood depth"
              >
                {[1, 2, 3, 4].map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-table text-ink-600">
              <span>Edge type</span>
              <select
                className="rounded-sm border border-line-200 bg-bg-panel px-2 py-1"
                value={edgeFilter}
                onChange={(e) => setEdgeFilter(e.target.value as GraphEdgeKind | "all")}
                aria-label="Edge type filter"
              >
                <option value="all">All</option>
                <option value="declared">Declared</option>
                <option value="observed">Observed</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-table text-ink-600">
              <input
                type="checkbox"
                checked={blastMode}
                onChange={(e) => {
                  setBlastMode(e.target.checked);
                  if (!e.target.checked) setBlastOriginId("");
                }}
              />
              Blast radius mode
            </label>
          </Toolbar>

          <div
            className="flex flex-wrap gap-4 border-t border-line-200 pt-3 text-table"
            role="group"
            aria-label="Graph legend"
          >
            <span className="flex items-center gap-2">
              <span className="inline-block h-0 w-8 border-t-2 border-ink-600" aria-hidden />
              Declared ({declaredCount})
            </span>
            <span className="flex items-center gap-2">
              <span
                className="inline-block h-0 w-8 border-t-2 border-dashed border-ok-fg"
                aria-hidden
              />
              Observed ({observedCount})
            </span>
            <span className="flex items-center gap-2 text-warn-fg">
              <span className="inline-block h-0 w-8 border-t-2 border-warn-fg" aria-hidden />
              Declared without observed ({gapsInView.length})
            </span>
          </div>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
        <Panel noPadding>
          <GraphCanvas
            nodes={visibleNodes}
            edges={visibleEdges}
            gapEdgeIds={gapEdgeIds}
            highlightNodeIds={highlightNodeIds}
            highlightEdgeIds={highlightEdgeIds}
            focusNodeId={effectiveFocus}
            onSelectNode={handleNodeSelect}
          />
        </Panel>

        <Panel title={blastMode ? "Blast radius" : "Neighbourhood"}>
          {blastMode ? (
            blastQuery.isLoading ? (
              <Skeleton height="6rem" />
            ) : blastQuery.isError ? (
              <ErrorState
                message={
                  blastQuery.error instanceof Error ? blastQuery.error.message : "Blast radius failed"
                }
                onRetry={() => void blastQuery.refetch()}
              />
            ) : blastOriginId && blastQuery.data ? (
              <div className="space-y-3 text-table">
                <p className="tabular-nums text-ink-900">
                  <span className="font-semibold">{(blastQuery.data.nodes ?? []).length}</span>{" "}
                  nodes reachable downstream
                </p>
                <ul className="max-h-64 overflow-auto scrollbar-thin space-y-1">
                  {(blastQuery.data.nodes ?? []).map((n) => (
                    <li key={n.node_id} className="text-ink-600">
                      {n.label}
                      <span className="ml-2 text-xs text-ink-400">depth {n.depth}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-table text-ink-600">Select a node on the graph to compute blast radius.</p>
            )
          ) : (
            <p className="text-table text-ink-600 tabular-nums">
              {visibleNodes.length} nodes · {visibleEdges.length} edges at depth {depth}
            </p>
          )}
        </Panel>
      </div>
    </div>
  );
}
