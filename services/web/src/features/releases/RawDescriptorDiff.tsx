import type { AgentVersion } from "@/api/types";

type RawDescriptorDiffProps = {
  fromVersion: AgentVersion | null;
  toVersion: AgentVersion | null;
  fromSemver: string | null;
  toSemver: string;
  isLoading: boolean;
};

export function RawDescriptorDiff({
  fromVersion,
  toVersion,
  fromSemver,
  toSemver,
  isLoading,
}: RawDescriptorDiffProps) {
  if (isLoading) {
    return <p className="text-table text-ink-400">Loading descriptor documents…</p>;
  }

  const fromJson = fromVersion
    ? JSON.stringify(fromVersion.descriptor_json, null, 2)
    : "// No prior version";
  const toJson = toVersion
    ? JSON.stringify(toVersion.descriptor_json, null, 2)
    : "// Version not found";

  return (
    <details className="group">
      <summary className="cursor-pointer text-sm font-medium text-ink-600 hover:text-ink-900 list-none flex items-center gap-2">
        <span className="text-ink-400 group-open:rotate-90 transition-transform inline-block" aria-hidden>
          ▶
        </span>
        Expand raw JSON side-by-side (contrast with semantic view above)
      </summary>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div>
          <p className="text-xs text-ink-600 mb-1 font-mono-data">{fromSemver ?? "—"}</p>
          <pre className="max-h-96 overflow-auto rounded-sm border border-line-200 bg-bg-sunk p-3 font-mono-data text-xs text-ink-900">
            {fromJson}
          </pre>
        </div>
        <div>
          <p className="text-xs text-ink-600 mb-1 font-mono-data">{toSemver}</p>
          <pre className="max-h-96 overflow-auto rounded-sm border border-line-200 bg-bg-sunk p-3 font-mono-data text-xs text-ink-900">
            {toJson}
          </pre>
        </div>
      </div>
    </details>
  );
}
