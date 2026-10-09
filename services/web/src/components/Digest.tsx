import { truncateMiddle } from "@/lib/formatters";
import { CopyButton } from "./CopyButton";

type DigestProps = {
  value: string;
  max?: number;
};

export function Digest({ value, max = 28 }: DigestProps) {
  return (
    <span className="inline-flex items-center gap-2 font-mono-data text-table text-ink-600">
      <span title={value}>{truncateMiddle(value, max)}</span>
      <CopyButton value={value} label="Copy digest" />
    </span>
  );
}
