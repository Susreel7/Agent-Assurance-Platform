type StackedBarSegment = {
  label: string;
  value: number;
  color: string;
};

type StackedBarProps = {
  segments: StackedBarSegment[];
  height?: number;
  ariaLabel: string;
};

export function StackedBar({ segments, height = 24, ariaLabel }: StackedBarProps) {
  const total = segments.reduce((s, seg) => s + seg.value, 0) || 1;
  return (
    <div
      className="flex w-full overflow-hidden rounded-sm"
      style={{ height }}
      role="img"
      aria-label={ariaLabel}
    >
      {segments.map((seg) => (
        <div
          key={seg.label}
          style={{ width: `${(seg.value / total) * 100}%`, background: seg.color }}
          title={`${seg.label}: ${seg.value}`}
        />
      ))}
    </div>
  );
}
