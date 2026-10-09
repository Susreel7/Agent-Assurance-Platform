import { CopyButton } from "./CopyButton";

type UrnProps = {
  value: string;
};

export function Urn({ value }: UrnProps) {
  return (
    <span className="inline-flex items-center gap-2 font-mono-data text-table text-ink-900">
      <span>{value}</span>
      <CopyButton value={value} label="Copy URN" />
    </span>
  );
}
