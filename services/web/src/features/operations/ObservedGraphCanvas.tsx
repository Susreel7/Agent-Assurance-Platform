/**
 * LangGraph topology as observed from run steps — Cytoscape, same stack as GraphCanvas.
 */

import cytoscape, { type Core, type ElementDefinition, type StylesheetStyle } from "cytoscape";
import { useEffect, useRef } from "react";
import type { ObservedGraph } from "@/api/types";

function failureClass(failures: number, executions: number): string {
  if (executions <= 0) return "fail-none";
  const rate = failures / executions;
  if (rate >= 0.1) return "fail-high";
  if (rate >= 0.03) return "fail-mid";
  return "fail-low";
}

const STYLES: StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "font-size": "9px",
      "text-wrap": "wrap",
      "text-max-width": "90px",
      color: "var(--ink-900)",
      "text-valign": "bottom",
      "text-margin-y": 6,
      "border-width": 2,
      "border-color": "#ffffff",
    },
  },
  { selector: "node.fail-low", style: { "background-color": "var(--ok-solid)" } },
  { selector: "node.fail-mid", style: { "background-color": "var(--warn-solid)" } },
  { selector: "node.fail-high", style: { "background-color": "var(--risk-solid)" } },
  { selector: "node.fail-none", style: { "background-color": "var(--mute-solid)" } },
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      "target-arrow-shape": "triangle",
      "line-color": "var(--ink-400)",
      "target-arrow-color": "var(--ink-400)",
      label: "data(label)",
      "font-size": "8px",
      color: "var(--ink-400)",
    },
  },
  {
    selector: "edge.warn",
    style: {
      "line-color": "var(--warn-solid)",
      "target-arrow-color": "var(--warn-solid)",
    },
  },
];

function toElements(graph: ObservedGraph): ElementDefinition[] {
  const maxExec = Math.max(...graph.nodes.map((n) => n.executions), 1);
  const maxTrav = Math.max(...graph.edges.map((e) => e.traversals), 1);
  const elements: ElementDefinition[] = [];

  for (const n of graph.nodes) {
    const size = 28 + (n.executions / maxExec) * 36;
    elements.push({
      group: "nodes",
      data: { id: n.name, label: `${n.name}\n${n.executions.toLocaleString()} exec` },
      classes: failureClass(n.failures, n.executions),
      style: { width: size, height: size },
    });
  }

  for (const e of graph.edges) {
    elements.push({
      group: "edges",
      data: {
        id: `${e.from_node}->${e.to_node}`,
        source: e.from_node,
        target: e.to_node,
        label: e.traversals.toLocaleString(),
      },
      classes: e.failures > 0 ? "warn" : "",
      style: { width: 1 + (e.traversals / maxTrav) * 5 },
    });
  }

  return elements;
}

type Props = {
  graph: ObservedGraph;
};

export function ObservedGraphCanvas({ graph }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: STYLES,
      layout: { name: "breadthfirst", directed: true, padding: 32 },
      minZoom: 0.25,
      maxZoom: 2.5,
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
    cy.batch(() => {
      cy.elements().remove();
      cy.add(toElements(graph));
    });
    cy.layout({ name: "breadthfirst", directed: true, padding: 32 }).run();
  }, [graph]);

  return (
    <div
      ref={containerRef}
      className="h-[min(60vh,520px)] w-full rounded-lg border border-line-200 bg-bg-sunk"
      role="img"
      aria-label="Observed LangGraph topology"
    />
  );
}
