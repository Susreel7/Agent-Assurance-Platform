import type { GraphEdge, GraphEdgeKind, GraphNode } from "@/api/types";

export function computeNeighbourhood(
  focusNodeId: string,
  depth: number,
  allEdges: readonly GraphEdge[],
): { nodeIds: Set<string>; edgeIds: Set<string> } {
  const nodeIds = new Set<string>([focusNodeId]);
  const edgeIds = new Set<string>();
  const clamped = Math.min(4, Math.max(1, depth));
  for (let d = 0; d < clamped; d++) {
    for (const e of allEdges) {
      if (nodeIds.has(e.source_id)) {
        nodeIds.add(e.target_id);
        edgeIds.add(e.id);
      }
      if (nodeIds.has(e.target_id)) {
        nodeIds.add(e.source_id);
        edgeIds.add(e.id);
      }
    }
  }
  return { nodeIds, edgeIds };
}

export type DeclaredObservedGap = {
  source_id: string;
  target_id: string;
  declared_edge_id: string;
};

export function computeDeclaredObservedGaps(
  edges: readonly GraphEdge[],
): DeclaredObservedGap[] {
  const observedPairs = new Set<string>();
  for (const e of edges) {
    if (e.kind === "observed") {
      observedPairs.add(`${e.source_id}\0${e.target_id}`);
    }
  }
  const gaps: DeclaredObservedGap[] = [];
  for (const e of edges) {
    if (e.kind !== "declared") continue;
    const key = `${e.source_id}\0${e.target_id}`;
    if (!observedPairs.has(key)) {
      gaps.push({ source_id: e.source_id, target_id: e.target_id, declared_edge_id: e.id });
    }
  }
  return gaps;
}

export function filterEdgesByKind(
  edges: readonly GraphEdge[],
  kind: GraphEdgeKind | "all",
): readonly GraphEdge[] {
  if (kind === "all") return edges;
  return edges.filter((e) => e.kind === kind);
}

export function nodesById(nodes: readonly GraphNode[]): Map<string, GraphNode> {
  const map = new Map<string, GraphNode>();
  for (const n of nodes) {
    map.set(n.id, n);
  }
  return map;
}
