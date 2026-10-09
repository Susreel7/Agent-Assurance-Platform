import { formatPrincipal } from "@/lib/formatters";

type PrincipalProps = {
  principalId: string;
};

export function Principal({ principalId }: PrincipalProps) {
  const prefix = principalId.split(":")[0] ?? "";
  const display = formatPrincipal(principalId);
  return (
    <span className="font-mono-data text-table" title={principalId}>
      <span className="text-ink-400">{prefix}:</span>
      {display}
    </span>
  );
}
