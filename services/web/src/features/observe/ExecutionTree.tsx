import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Icon } from "@/components/Icon";
import {
  executionTypeLabel,
  formatDuration,
  type ExecutionGraphItem,
  type ExecutionVisualStatus,
} from "./executionGraphModel";

type Props = {
  items: ExecutionGraphItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

type TreeRow = {
  item: ExecutionGraphItem;
  level: number;
  parentId: string | null;
  hasChildren: boolean;
};

const statusDotClass: Record<ExecutionVisualStatus, string> = {
  queued: "bg-mute-solid",
  running: "bg-info-solid",
  succeeded: "bg-ok-solid",
  failed: "bg-risk-solid",
  skipped: "bg-ink-300",
  retry: "bg-warn-solid",
  waiting: "bg-warn-solid",
  unknown: "bg-mute-solid",
};

function flattenTree(items: ExecutionGraphItem[], expanded: Set<string>): TreeRow[] {
  const byId = new Map(items.map((item) => [item.id, item]));
  const children = new Map<string, ExecutionGraphItem[]>();
  for (const item of items) {
    if (!item.parentId || !byId.has(item.parentId)) continue;
    children.set(item.parentId, [...(children.get(item.parentId) ?? []), item]);
  }
  for (const values of children.values()) {
    values.sort((left, right) => (left.startTime ?? "").localeCompare(right.startTime ?? ""));
  }

  let roots = items.filter((item) => !item.parentId || !byId.has(item.parentId));
  if (roots.length === 0) roots = items;
  const rows: TreeRow[] = [];
  const visited = new Set<string>();
  const walk = (item: ExecutionGraphItem, level: number, parentId: string | null) => {
    if (visited.has(item.id)) return;
    visited.add(item.id);
    const itemChildren = children.get(item.id) ?? [];
    rows.push({ item, level, parentId, hasChildren: itemChildren.length > 0 });
    if (!expanded.has(item.id)) return;
    for (const child of itemChildren) walk(child, level + 1, item.id);
  };
  for (const root of roots) walk(root, 1, null);
  for (const item of items) {
    if (!visited.has(item.id)) walk(item, 1, null);
  }
  return rows;
}

export function ExecutionTree({ items, selectedId, onSelect }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const initializedRef = useRef(false);
  const itemRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    if (initializedRef.current || items.length === 0) return;
    initializedRef.current = true;
    const parentIds = new Set(items.flatMap((item) => (item.parentId ? [item.parentId] : [])));
    setExpanded(new Set(items.filter((item) => parentIds.has(item.id)).map((item) => item.id)));
  }, [items]);

  const rows = useMemo(() => flattenTree(items, expanded), [expanded, items]);
  const rowIndex = useMemo(
    () => new Map(rows.map((row, index) => [row.item.id, index])),
    [rows],
  );

  const toggle = (id: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const focusRow = (index: number) => {
    const row = rows[index];
    if (row) itemRefs.current.get(row.item.id)?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, row: TreeRow) => {
    const index = rowIndex.get(row.item.id) ?? 0;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusRow(Math.min(rows.length - 1, index + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusRow(Math.max(0, index - 1));
    } else if (event.key === "ArrowRight" && row.hasChildren) {
      event.preventDefault();
      if (!expanded.has(row.item.id)) toggle(row.item.id);
      else focusRow(index + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (row.hasChildren && expanded.has(row.item.id)) toggle(row.item.id);
      else if (row.parentId) itemRefs.current.get(row.parentId)?.focus();
    } else if (event.key === " " && row.hasChildren) {
      event.preventDefault();
      toggle(row.item.id);
    } else if (event.key === "Enter") {
      event.preventDefault();
      onSelect(row.item.id);
    }
  };

  if (items.length === 0) {
    return <p className="p-6 text-sm text-ink-400">No observations were recorded.</p>;
  }

  return (
    <div className="h-full min-h-0 overflow-auto bg-bg-panel p-2" role="tree" aria-label="Agent execution tree">
      {rows.map((row) => {
        const isExpanded = expanded.has(row.item.id);
        return (
          <div
            key={row.item.id}
            role="treeitem"
            aria-level={row.level}
            aria-expanded={row.hasChildren ? isExpanded : undefined}
            aria-selected={selectedId === row.item.id}
          >
            <button
              ref={(node) => {
                if (node) itemRefs.current.set(row.item.id, node);
                else itemRefs.current.delete(row.item.id);
              }}
              type="button"
              tabIndex={selectedId === row.item.id || (!selectedId && row === rows[0]) ? 0 : -1}
              onClick={() => onSelect(row.item.id)}
              onDoubleClick={() => row.hasChildren && toggle(row.item.id)}
              onKeyDown={(event) => handleKeyDown(event, row)}
              className={`group flex min-h-9 w-full items-center gap-2 border-l-2 px-2 text-left text-xs hover:bg-bg-hover focus:outline-none focus:ring-1 focus:ring-inset focus:ring-info-fg ${
                selectedId === row.item.id
                  ? "border-info-fg bg-info-bg text-ink-900"
                  : "border-transparent text-ink-700"
              }`}
              style={{ paddingLeft: `${8 + (row.level - 1) * 20}px` }}
            >
              <span
                className="flex h-5 w-5 shrink-0 items-center justify-center text-ink-400"
                onClick={(event) => {
                  if (!row.hasChildren) return;
                  event.stopPropagation();
                  toggle(row.item.id);
                }}
              >
                {row.hasChildren ? (
                  <Icon name={isExpanded ? "chevronDown" : "chevronRight"} size={13} />
                ) : (
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${statusDotClass[row.item.status]}`}
                  />
                )}
              </span>
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${statusDotClass[row.item.status]}`}
              />
              <span className="min-w-0 flex-1 truncate font-medium">{row.item.label}</span>
              <span className="shrink-0 text-micro uppercase tracking-wide text-ink-400">
                {executionTypeLabel(row.item.type)}
              </span>
              <span className="w-16 shrink-0 text-right font-mono-data text-micro text-ink-400">
                {formatDuration(row.item.durationMs)}
              </span>
            </button>
          </div>
        );
      })}
    </div>
  );
}
