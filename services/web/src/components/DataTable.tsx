import clsx from "clsx";
import { useMemo, useState } from "react";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { TableSkeleton } from "./Skeleton";

export type ColumnDef<T> = {
  id: string;
  header: string;
  accessor?: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number;
  className?: string;
  align?: "left" | "right";
};

type SortState = {
  columnId: string;
  direction: "asc" | "desc";
};

type DataTableProps<T> = {
  columns: ColumnDef<T>[];
  // `readonly` because the table only ever reads. It also lets callers pass a shared
  // frozen empty array while a query is pending without cloning it.
  data: readonly T[];
  rowKey: (row: T) => string;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyDescription?: string;
  onRowClick?: (row: T) => void;
  stickyHeader?: boolean;
};

export function DataTable<T>({
  columns,
  data,
  rowKey,
  isLoading,
  error,
  onRetry,
  emptyTitle = "No records",
  emptyDescription,
  onRowClick,
  stickyHeader = true,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<SortState | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return data;
    const col = columns.find((c) => c.id === sort.columnId);
    if (!col?.sortValue) return data;
    const copy = [...data];
    copy.sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (av < bv) return sort.direction === "asc" ? -1 : 1;
      if (av > bv) return sort.direction === "asc" ? 1 : -1;
      return 0;
    });
    return copy;
  }, [columns, data, sort]);

  function toggleSort(columnId: string, sortable: boolean) {
    if (!sortable) return;
    setSort((prev) => {
      if (prev?.columnId !== columnId) return { columnId, direction: "asc" };
      return { columnId, direction: prev.direction === "asc" ? "desc" : "asc" };
    });
  }

  if (isLoading) {
    return (
      <div className="p-4">
        <TableSkeleton rows={8} cols={columns.length} />
      </div>
    );
  }

  if (error) {
    return <ErrorState message={error} onRetry={onRetry} />;
  }

  if (sorted.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <div className="overflow-auto scrollbar-thin max-h-[70vh]">
      <table>
        <thead className={clsx(stickyHeader && "sticky top-0 z-10")}>
          <tr>
            {columns.map((col) => {
              const sortable = Boolean(col.sortValue);
              const active = sort?.columnId === col.id;
              return (
                <th
                  key={col.id}
                  scope="col"
                  className={clsx(
                    "px-3 py-2 whitespace-nowrap",
                    col.className,
                    col.align === "right" && "text-right",
                    sortable && "cursor-pointer select-none",
                  )}
                  onClick={() => toggleSort(col.id, sortable)}
                  aria-sort={
                    active ? (sort?.direction === "asc" ? "ascending" : "descending") : undefined
                  }
                >
                  {col.header}
                  {active ? (sort?.direction === "asc" ? " ↑" : " ↓") : null}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const key = rowKey(row);
            return (
              <tr
                key={key}
                className={clsx(onRowClick && "cursor-pointer hover:bg-bg-sunk")}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
              >
                {columns.map((col) => (
                  <td
                    key={col.id}
                    className={clsx("px-3 py-2", col.className, col.align === "right" && "text-right")}
                  >
                    {col.accessor ? col.accessor(row) : null}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
