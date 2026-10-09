import type { ExecutionObservation } from "@/api/types";
import {
  normalizeExecutionStatus,
  type ExecutionVisualStatus,
} from "./executionGraphModel";

export type TimelineSpan = {
  id: string;
  parentId: string | null;
  label: string;
  type: string;
  status: ExecutionVisualStatus;
  startMs: number;
  endMs: number;
  durationMs: number;
  selfMs: number;
  depth: number;
  isCritical: boolean;
};

export type TimelineAnalysis = {
  spans: TimelineSpan[];
  startMs: number;
  endMs: number;
  durationMs: number;
  observedMs: number;
  criticalPathMs: number;
  criticalSpanIds: Set<string>;
  maxParallelism: number;
  omittedCount: number;
};

type Interval = Omit<TimelineSpan, "selfMs" | "depth" | "isCritical">;
type ScoredPath = { score: number; ids: Set<string> };

function timestamp(value?: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function unionDuration(ranges: Array<[number, number]>): number {
  if (ranges.length === 0) return 0;
  const sorted = [...ranges].sort((left, right) => left[0] - right[0]);
  let [rangeStart, rangeEnd] = sorted[0]!;
  let total = 0;
  for (let index = 1; index < sorted.length; index += 1) {
    const [start, end] = sorted[index]!;
    if (start <= rangeEnd) {
      rangeEnd = Math.max(rangeEnd, end);
    } else {
      total += rangeEnd - rangeStart;
      rangeStart = start;
      rangeEnd = end;
    }
  }
  return total + rangeEnd - rangeStart;
}

function weightedSchedule(paths: Array<{ interval: Interval; path: ScoredPath }>): ScoredPath {
  if (paths.length === 0) return { score: 0, ids: new Set() };
  const sorted = [...paths].sort(
    (left, right) => left.interval.endMs - right.interval.endMs,
  );
  const previous = sorted.map((entry, index) => {
    let compatible = index - 1;
    while (
      compatible >= 0 &&
      sorted[compatible]!.interval.endMs > entry.interval.startMs
    ) {
      compatible -= 1;
    }
    return compatible;
  });
  const best: ScoredPath[] = [];
  for (let index = 0; index < sorted.length; index += 1) {
    const previousIndex = previous[index] ?? -1;
    const prior =
      previousIndex >= 0
        ? best[previousIndex]!
        : { score: 0, ids: new Set<string>() };
    const current = sorted[index]!;
    const included = {
      score: prior.score + current.path.score,
      ids: new Set([...prior.ids, ...current.path.ids]),
    };
    const excluded =
      index > 0 ? best[index - 1]! : { score: 0, ids: new Set<string>() };
    best.push(included.score >= excluded.score ? included : excluded);
  }
  return best.at(-1) ?? { score: 0, ids: new Set() };
}

function concurrency(intervals: Interval[]): number {
  const points = intervals.flatMap((interval) => [
    { time: interval.startMs, delta: 1 },
    { time: interval.endMs, delta: -1 },
  ]);
  points.sort((left, right) => left.time - right.time || left.delta - right.delta);
  let active = 0;
  let maximum = 0;
  for (const point of points) {
    active += point.delta;
    maximum = Math.max(maximum, active);
  }
  return maximum;
}

export function analyzeExecutionTimeline(
  observations: ExecutionObservation[],
  nowMs = Date.now(),
): TimelineAnalysis {
  let omittedCount = 0;
  const intervals: Interval[] = [];
  for (const observation of observations) {
    const startMs = timestamp(observation.start_time);
    if (startMs == null) {
      omittedCount += 1;
      continue;
    }
    const explicitEnd = timestamp(observation.end_time);
    const measuredDuration = Math.max(0, observation.duration_ms ?? 0);
    const endMs = Math.max(
      startMs,
      explicitEnd ?? (measuredDuration > 0 ? startMs + measuredDuration : nowMs),
    );
    intervals.push({
      id: observation.span_id,
      parentId: observation.parent_span_id ?? null,
      label: observation.operation_name,
      type: (observation.observation_type ?? observation.kind ?? "unknown").toLowerCase(),
      status: normalizeExecutionStatus(
        observation.is_terminal
          ? observation.outcome ?? "succeeded"
          : observation.outcome ?? "running",
      ),
      startMs,
      endMs,
      durationMs: endMs - startMs,
    });
  }

  if (intervals.length === 0) {
    return {
      spans: [],
      startMs: 0,
      endMs: 0,
      durationMs: 0,
      observedMs: 0,
      criticalPathMs: 0,
      criticalSpanIds: new Set(),
      maxParallelism: 0,
      omittedCount,
    };
  }

  const byId = new Map(intervals.map((interval) => [interval.id, interval]));
  const children = new Map<string, Interval[]>();
  const roots: Interval[] = [];
  for (const interval of intervals) {
    if (interval.parentId && byId.has(interval.parentId)) {
      const siblings = children.get(interval.parentId) ?? [];
      siblings.push(interval);
      children.set(interval.parentId, siblings);
    } else {
      roots.push(interval);
    }
  }

  const selfById = new Map<string, number>();
  for (const interval of intervals) {
    const covered = unionDuration(
      (children.get(interval.id) ?? [])
        .map(
          (child) =>
            [
              Math.max(interval.startMs, child.startMs),
              Math.min(interval.endMs, child.endMs),
            ] as [number, number],
        )
        .filter(([start, end]) => end > start),
    );
    selfById.set(interval.id, Math.max(0, interval.durationMs - covered));
  }

  const visiting = new Set<string>();
  const scorePath = (interval: Interval): ScoredPath => {
    if (visiting.has(interval.id)) {
      return { score: selfById.get(interval.id) ?? 0, ids: new Set([interval.id]) };
    }
    visiting.add(interval.id);
    const childPath = weightedSchedule(
      (children.get(interval.id) ?? []).map((child) => ({
        interval: child,
        path: scorePath(child),
      })),
    );
    visiting.delete(interval.id);
    return {
      score: (selfById.get(interval.id) ?? 0) + childPath.score,
      ids: new Set([interval.id, ...childPath.ids]),
    };
  };
  const critical = weightedSchedule(
    roots.map((root) => ({ interval: root, path: scorePath(root) })),
  );

  const depthFor = (interval: Interval): number => {
    let depth = 0;
    let parentId = interval.parentId;
    const seen = new Set([interval.id]);
    while (parentId && byId.has(parentId) && !seen.has(parentId)) {
      seen.add(parentId);
      depth += 1;
      parentId = byId.get(parentId)?.parentId ?? null;
    }
    return depth;
  };
  const startMs = Math.min(...intervals.map((interval) => interval.startMs));
  const endMs = Math.max(...intervals.map((interval) => interval.endMs));
  const spans = intervals.map<TimelineSpan>((interval) => ({
      ...interval,
      selfMs: selfById.get(interval.id) ?? interval.durationMs,
      depth: depthFor(interval),
      isCritical: critical.ids.has(interval.id),
    }));
  spans.sort(
      (left, right) =>
        left.startMs - right.startMs ||
        left.depth - right.depth ||
        left.endMs - right.endMs,
  );

  return {
    spans,
    startMs,
    endMs,
    durationMs: endMs - startMs,
    observedMs: intervals.reduce((total, interval) => total + interval.durationMs, 0),
    criticalPathMs: critical.score,
    criticalSpanIds: critical.ids,
    maxParallelism: concurrency(intervals),
    omittedCount,
  };
}
