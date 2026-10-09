import cytoscape, { type Core, type ElementDefinition, type StylesheetStyle } from "cytoscape";
import { useEffect, useRef } from "react";
import type { GraphEdge, GraphNode, GraphNodeKind } from "@/api/types";

const NODE_SHAPE = {
  agent: "round-rectangle",
  model: "ellipse",
  tool: "diamond",
  mcp_server: "hexagon",
  data_source: "rectangle",
  dataset: "barrel",
  sub_agent: "round-rectangle",
  external_service: "triangle",
} as const satisfies Record<GraphNodeKind, string>;

const GRAPH_STYLES: StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "font-size": "10px",
      "text-wrap": "wrap",
      "text-max-width": "80px",
      "background-color": "#ffffff",
      "border-width": 1.5,
      "border-color": "var(--line-300)",
      color: "var(--ink-900)",
      "text-valign": "bottom",
      "text-margin-y": 4,
      width: 36,
      height: 36,
    },
  },
  ...(Object.keys(NODE_SHAPE) as GraphNodeKind[]).map((kind) => ({
    selector: `node[kind = "${kind}"]`,
    style: { shape: NODE_SHAPE[kind] },
  })),
  {
    selector: "node.focus",
    style: {
      "border-color": "var(--info-fg)",
      "border-width": 2.5,
    },
  },
  {
    selector: "node.blast",
    style: {
      "background-color": "var(--info-bg)",
      "border-color": "var(--info-fg)",
    },
  },
  {
    selector: "node.dim",
    style: { opacity: 0.25 },
  },
  {
    selector: "edge",
    style: {
      width: 1.5,
      "line-color": "var(--ink-400)",
      "target-arrow-color": "var(--ink-400)",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      label: "data(label)",
      "font-size": "8px",
      color: "var(--ink-400)",
    },
  },
  {
    selector: "edge.declared",
    style: {
      "line-style": "solid",
      "line-color": "var(--ink-600)",
      "target-arrow-color": "var(--ink-600)",
    },
  },
  {
    selector: "edge.observed",
    style: {
      "line-style": "dashed",
      "line-dash-pattern": [6, 4],
      "line-color": "var(--ok-fg)",
      "target-arrow-color": "var(--ok-fg)",
    },
  },
  {
    selector: "edge.gap",
    style: {
      "line-color": "var(--warn-fg)",
      "target-arrow-color": "var(--warn-fg)",
      width: 2.5,
    },
  },
  {
    selector: "edge.blast",
    style: { width: 2.5, "line-color": "var(--info-fg)", "target-arrow-color": "var(--info-fg)" },
  },
  {
    selector: "edge.dim",
    style: { opacity: 0.15 },
  },
];

type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  gapEdgeIds: Set<string>;
  highlightNodeIds: Set<string>;
  highlightEdgeIds: Set<string>;
  focusNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
};

function toElements(
  nodes: GraphNode[],
  edges: GraphEdge[],
  gapEdgeIds: Set<string>,
  highlightNodeIds: Set<string>,
  highlightEdgeIds: Set<string>,
  focusNodeId: string | null,
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];
  for (const n of nodes) {
    const inBlast = highlightNodeIds.size > 0 && highlightNodeIds.has(n.id);
    const dimmed = highlightNodeIds.size > 0 && !highlightNodeIds.has(n.id);
    elements.push({
      group: "nodes",
      data: { id: n.id, label: n.label, kind: n.kind },
      classes: [
        focusNodeId === n.id ? "focus" : "",
        inBlast ? "blast" : "",
        dimmed ? "dim" : "",
      ]
        .filter(Boolean)
        .join(" "),
    });
  }
  for (const e of edges) {
    const isGap = gapEdgeIds.has(e.id);
    const inBlast = highlightEdgeIds.size > 0 && highlightEdgeIds.has(e.id);
    const dimmed = highlightEdgeIds.size > 0 && !highlightEdgeIds.has(e.id);
    elements.push({
      group: "edges",
      data: {
        id: e.id,
        source: e.source_id,
        target: e.target_id,
        kind: e.kind,
        label: e.label ?? "",
      },
      classes: [
        e.kind,
        isGap ? "gap" : "",
        inBlast ? "blast" : "",
        dimmed ? "dim" : "",
      ]
        .filter(Boolean)
        .join(" "),
    });
  }
  return elements;
}

export function GraphCanvas({
  nodes,
  edges,
  gapEdgeIds,
  highlightNodeIds,
  highlightEdgeIds,
  focusNodeId,
  onSelectNode,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  // The tap handler is registered once on mount, so it would otherwise close over the
  // first `onSelectNode` forever. Holding the callback in a ref and syncing it in an
  // effect keeps the handler current without tearing down and rebuilding the graph
  // every time the parent re-renders — which on a large estate is seconds of layout.
  const onSelectRef = useRef(onSelectNode);
  useEffect(() => {
    onSelectRef.current = onSelectNode;
  }, [onSelectNode]);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: GRAPH_STYLES,
      layout: { name: "cose", animate: false, padding: 24 },
      minZoom: 0.2,
      maxZoom: 3,
    });
    cy.on("tap", "node", (evt) => {
      const id = evt.target.id();
      onSelectRef.current(id);
    });
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const els = toElements(nodes, edges, gapEdgeIds, highlightNodeIds, highlightEdgeIds, focusNodeId);
    cy.batch(() => {
      cy.elements().remove();
      cy.add(els);
    });
    cy.layout({ name: "cose", animate: false, padding: 24 }).run();
  }, [nodes, edges, gapEdgeIds, highlightNodeIds, highlightEdgeIds, focusNodeId]);

  return (
    <div
      ref={containerRef}
      className="h-[min(70vh,640px)] w-full border border-line-200 bg-bg-sunk"
      role="img"
      aria-label="Agent dependency graph"
    />
  );
}
