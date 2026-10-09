import clsx from "clsx";

type SkeletonProps = {
  className?: string;
  width?: string | number;
  height?: string | number;
};

export function Skeleton({ className, width = "100%", height = "1rem" }: SkeletonProps) {
  return (
    <div
      className={clsx("animate-pulse rounded-sm bg-bg-sunk", className)}
      style={{ width, height }}
      aria-hidden
    />
  );
}

export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }, (_, c) => (
            <Skeleton key={c} height="0.875rem" className="flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}
