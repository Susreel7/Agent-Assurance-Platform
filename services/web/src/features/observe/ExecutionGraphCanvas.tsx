import cytoscape, { type Core, type ElementDefinition, type StylesheetStyle } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import {
  executionTypeLabel,
  formatDuration,
  type ExecutionGraphItem,
  type ExecutionVisualStatus,
} from "./executionGraphModel";

const TYPE_SHAPES: Record<string, cytoscape.Css.NodeShape> = {
  agent: "round-rectangle",
  node: "round-rectangle",
  generation: "ellipse",
  tool: "diamond",
  sdk: "hexagon",
  mcp: "hexagon",
  a2a: "round-rectangle",
  human_approval: "round-tag",
  retrieval: "rectangle",
  chain: "round-rectangle",
  http: "tag",
  database: "barrel",
  state_transition: "round-tag",
  event: "ellipse",
  evaluation: "round-rectangle",
  error: "diamond",
  retry: "rhomboid",
};

const GRAPH_STYLES: StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      shape: "round-rectangle",
      width: 118,
      height: 48,
      padding: "5px",
      "font-size": "10px",
      "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
      "font-weight": 500,
      "text-wrap": "wrap",
      "text-max-width": "104px",
      "text-valign": "center",
      "text-halign": "center",
      color: "#20252c",
      "background-color": "#ffffff",
      "border-width": 1.5,
      "border-color": "#cfd4dc",
      "overlay-opacity": 0,
    },
  },
  ...Object.entries(TYPE_SHAPES).map(([type, shape]) => ({
    selector: `node[type = "${type}"]`,
    style: { shape },
  })),
  {
    selector: "node[type = 'event'], node[type = 'state_transition'], node[type = 'retry']",
    style: { width: 92, height: 34, "font-size": "9px", "background-color": "#f7f8fa" },
  },
  {
    selector: "node.status-succeeded",
    style: { "border-color": "#23855b", "background-color": "#f1faf5" },
  },
  {
    selector: "node.status-running",
    style: { "border-color": "#3973c6", "background-color": "#f1f6fd" },
  },
  {
    selector: "node.status-queued, node.status-unknown",
    style: { "border-color": "#a3aab5", "border-style": "dashed" },
  },
  {
    selector: "node.status-failed",
    style: { "border-color": "#c8413b", "background-color": "#fff4f3", "border-width": 2.5 },
  },
  {
    selector: "node.status-retry",
    style: { "border-color": "#b56b13", "background-color": "#fff8ec", "border-width": 2 },
  },
  {
    selector: "node.status-waiting",
    style: { "border-color": "#8a6ac8", "background-color": "#f8f4ff" },
  },
  {
    selector: "node.status-skipped",
    style: { opacity: 0.55, "border-style": "dashed" },
  },
  {
    selector: "node.orphan",
    style: { "border-color": "#b56b13", "border-style": "dotted" },
  },
  {
    selector: "node.selected",
    style: { "border-color": "#1769c2", "border-width": 3, "underlay-color": "#1769c2", "underlay-opacity": 0.08, "underlay-padding": 5 },
  },
  { selector: "node.dimmed", style: { opacity: 0.18 } },
  {
    selector: "edge",
    style: {
      width: 1.4,
      "curve-style": "bezier",
      "line-color": "#b9c0ca",
      "target-arrow-color": "#b9c0ca",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.75,
      "overlay-opacity": 0,
    },
  },
  {
    selector: "edge.failed-path",
    style: { width: 2.2, "line-color": "#c8413b", "target-arrow-color": "#c8413b" },
  },
  {
    selector: "edge.retry-path",
    style: {
      width: 2,
      "line-style": "dashed",
      "line-color": "#b56b13",
      "target-arrow-color": "#b56b13",
    },
  },
  { selector: "edge.dimmed", style: { opacity: 0.12 } },
];

type Props = {
  items: ExecutionGraphItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  hasCycle?: boolean;
};

const controlClass =
  "inline-flex h-8 items-center gap-1.5 border border-line-200 bg-bg-panel px-2 text-xs text-ink-600 hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40";

function ancestorIds(items: ExecutionGraphItem[], targetStatuses: Set<ExecutionVisualStatus>) {
  const byId = new Map(items.map((item) => [item.id, item]));
  const highlighted = new Set<string>();
  for (const item of items) {
    if (!targetStatuses.has(item.status)) continue;
    let current: ExecutionGraphItem | undefined = item;
    while (current && !highlighted.has(current.id)) {
      highlighted.add(current.id);
      current = current.parentId ? byId.get(current.parentId) : undefined;
    }
  }
  return highlighted;
}

function hiddenDescendants(items: ExecutionGraphItem[], collapsed: Set<string>) {
  const children = new Map<string, string[]>();
  for (const item of items) {
    if (!item.parentId) continue;
    children.set(item.parentId, [...(children.get(item.parentId) ?? []), item.id]);
  }
  const hidden = new Set<string>();
  const visit = (id: string) => {
    for (const child of children.get(id) ?? []) {
      hidden.add(child);
      visit(child);
    }
  };
  for (const id of collapsed) visit(id);
  return hidden;
}

function flowParentIds(items: ExecutionGraphItem[]): Map<string, string | null> {
  const graphItems = items.filter((item) => item.graphVisible !== false);
  const ids = new Set(graphItems.map((item) => item.id));
  const root =
    graphItems.find(
      (item) =>
        item.type === "agent" && (!item.parentId || !ids.has(item.parentId)),
    ) ?? graphItems.find((item) => !item.parentId || !ids.has(item.parentId));
  const parents = new Map(
    graphItems.map((item) => [
      item.id,
      item.parentId && ids.has(item.parentId) ? item.parentId : null,
    ]),
  );
  if (!root) return parents;

  const topLevel = graphItems
    .filter((item) => item.parentId === root.id)
    .sort((left, right) => {
      const timeOrder = (left.startTime ?? "").localeCompare(right.startTime ?? "");
      return timeOrder || left.id.localeCompare(right.id);
    });
  const workflowStages = topLevel.filter((item) =>
    ["node", "evaluation", "event"].includes(item.type),
  );
  let previousId = root.id;
  for (const item of workflowStages) {
    parents.set(item.id, previousId);
    previousId = item.id;
  }
  for (const item of topLevel) {
    if (workflowStages.includes(item)) continue;
    const itemTime = item.startTime ?? "";
    let containingStage: ExecutionGraphItem | undefined;
    for (let index = workflowStages.length - 1; index >= 0; index -= 1) {
      const stage = workflowStages[index];
      if (stage && (stage.startTime ?? "") <= itemTime) {
        containingStage = stage;
        break;
      }
    }
    parents.set(item.id, containingStage?.id ?? root.id);
  }
  return parents;
}

export function ExecutionGraphCanvas({ items, selectedId, onSelect, hasCycle = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [pathMode, setPathMode] = useState<"all" | "failed" | "retry">("all");

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const types = useMemo(
    () => [...new Set(items.map((item) => item.type))].sort(),
    [items],
  );
  const hidden = useMemo(() => hiddenDescendants(items, collapsed), [items, collapsed]);
  const pathIds = useMemo(
    () =>
      pathMode === "failed"
        ? ancestorIds(items, new Set(["failed"]))
        : pathMode === "retry"
          ? ancestorIds(items, new Set(["retry"]))
          : new Set<string>(),
    [items, pathMode],
  );
  const graphParents = useMemo(() => flowParentIds(items), [items]);

  const elements = useMemo(() => {
    const ids = new Set(items.map((item) => item.id));
    const visible = items.filter((item) => {
      if (item.graphVisible === false) return false;
      if (hidden.has(item.id)) return false;
      if (typeFilter !== "all" && item.type !== typeFilter) return false;
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (pathMode !== "all" && !pathIds.has(item.id)) return false;
      return true;
    });
    const visibleIds = new Set(visible.map((item) => item.id));
    const normalizedQuery = query.trim().toLowerCase();
    const output: ElementDefinition[] = visible.map((item) => {
      const dimmed =
        normalizedQuery.length > 0 &&
        !`${item.label} ${item.type} ${item.status}`.toLowerCase().includes(normalizedQuery);
      const orphan = Boolean(item.parentId && !ids.has(item.parentId));
      return {
        group: "nodes",
        data: {
          id: item.id,
          type: item.type,
          label: `${item.label}\n${formatDuration(item.durationMs)}`,
        },
        classes: [
          `status-${item.status}`,
          item.id === selectedId ? "selected" : "",
          dimmed ? "dimmed" : "",
          orphan ? "orphan" : "",
        ]
          .filter(Boolean)
          .join(" "),
      };
    });
    for (const item of visible) {
      const graphParentId = graphParents.get(item.id);
      if (!graphParentId || !visibleIds.has(graphParentId)) continue;
      const dimmed =
        normalizedQuery.length > 0 &&
        !pathIds.has(item.id) &&
        !pathIds.has(graphParentId) &&
        !`${item.label} ${item.type}`.toLowerCase().includes(normalizedQuery);
      output.push({
        group: "edges",
        data: {
          id: `${graphParentId}->${item.id}`,
          source: graphParentId,
          target: item.id,
        },
        classes: [
          item.status === "failed" ? "failed-path" : "",
          item.status === "retry" ? "retry-path" : "",
          dimmed ? "dimmed" : "",
        ]
          .filter(Boolean)
          .join(" "),
      });
    }
    return output;
  }, [
    graphParents,
    hidden,
    items,
    pathIds,
    pathMode,
    query,
    selectedId,
    statusFilter,
    typeFilter,
  ]);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: GRAPH_STYLES,
      layout: {
        name: "breadthfirst",
        directed: true,
        padding: 32,
        spacingFactor: 1.3,
        transform: (_node, position) => ({ x: position.y, y: position.x }),
      },
      minZoom: 0.18,
      maxZoom: 3,
      wheelSensitivity: 0.18,
    });
    cy.on("tap", "node", (event) => onSelectRef.current(event.target.id()));
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
      cy.add(elements);
    });
    cy.layout(
      hasCycle
        ? { name: "cose", animate: false, padding: 32 }
        : {
            name: "breadthfirst",
            directed: true,
            padding: 32,
            spacingFactor: 1.3,
            transform: (_node, position) => ({ x: position.y, y: position.x }),
          },
    ).run();
  }, [elements, hasCycle]);

  const toggleCollapse = () => {
    if (!selectedId) return;
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(selectedId)) next.delete(selectedId);
      else next.add(selectedId);
      return next;
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line-200 bg-bg-sunk p-2">
        <label className="relative min-w-40 flex-1">
          <Icon name="search" size={14} className="absolute left-2 top-2 text-ink-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find node"
            aria-label="Find execution node"
            className="h-8 w-full border border-line-200 bg-bg-panel pl-7 pr-2 text-xs outline-none focus:border-info-fg"
          />
        </label>
        <select
          value={typeFilter}
          onChange={(event) => setTypeFilter(event.target.value)}
          aria-label="Filter by observation type"
          className={controlClass}
        >
          <option value="all">All types</option>
          {types.map((type) => (
            <option key={type} value={type}>
              {executionTypeLabel(type)}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          aria-label="Filter by status"
          className={controlClass}
        >
          <option value="all">All states</option>
          {["queued", "running", "succeeded", "failed", "skipped", "retry", "waiting"].map(
            (status) => (
              <option key={status} value={status}>
                {executionTypeLabel(status)}
              </option>
            ),
          )}
        </select>
        <button
          type="button"
          className={controlClass}
          onClick={() => cyRef.current?.fit(undefined, 28)}
          title="Fit graph to viewport"
        >
          Fit
        </button>
        <button
          type="button"
          className={controlClass}
          disabled={!selectedId}
          onClick={() => {
            const cy = cyRef.current;
            if (!cy || !selectedId) return;
            const node = cy.getElementById(selectedId);
            if (node.length) cy.animate({ center: { eles: node } }, { duration: 180 });
          }}
          title="Center the selected node"
        >
          Focus
        </button>
        <button
          type="button"
          className={controlClass}
          disabled={!selectedId}
          onClick={toggleCollapse}
          title="Collapse or expand the selected subtree"
        >
          {selectedId && collapsed.has(selectedId) ? "Expand" : "Collapse"}
        </button>
        {(["all", "failed", "retry"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            className={`${controlClass} ${pathMode === mode ? "border-info-fg text-info-fg" : ""}`}
            onClick={() => setPathMode(mode)}
          >
            {mode === "all" ? "All paths" : `${executionTypeLabel(mode)} path`}
          </button>
        ))}
      </div>
      <div
        ref={containerRef}
        className="min-h-0 flex-1 bg-bg-panel"
        role="img"
        aria-label="Interactive agent execution graph. Use the adjacent tree for keyboard navigation."
      />
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line-200 px-3 py-2 text-micro text-ink-400">
        <span>{elements.filter((element) => element.group === "nodes").length} visible</span>
        <span>Scroll to zoom · drag to pan · select a node for details</span>
        {collapsed.size > 0 ? (
          <button type="button" className="text-info-fg hover:underline" onClick={() => setCollapsed(new Set())}>
            Expand all ({collapsed.size})
          </button>
        ) : null}
      </div>
    </div>
  );
}
