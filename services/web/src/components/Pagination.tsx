type PaginationProps = {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
};

export function Pagination({ total, limit, offset, onPageChange }: PaginationProps) {
  const page = Math.floor(offset / limit) + 1;
  const pageCount = Math.max(1, Math.ceil(total / limit));
  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  return (
    <nav className="flex items-center justify-between gap-4 text-table text-ink-600" aria-label="Pagination">
      <span>
        {total === 0 ? "No results" : `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!canPrev}
          className="rounded-sm border border-line-200 px-2 py-1 disabled:opacity-40"
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          aria-label="Previous page"
        >
          Previous
        </button>
        <span className="px-2 py-1 tabular-nums">
          Page {page} of {pageCount}
        </span>
        <button
          type="button"
          disabled={!canNext}
          className="rounded-sm border border-line-200 px-2 py-1 disabled:opacity-40"
          onClick={() => onPageChange(offset + limit)}
          aria-label="Next page"
        >
          Next
        </button>
      </div>
    </nav>
  );
}
