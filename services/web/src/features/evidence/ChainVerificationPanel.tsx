import type { ChainVerification, EvidenceBatch, InclusionProof } from "@/api/types";
import { Digest } from "@/components/Digest";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";

type ChainVerificationPanelProps = {
  chain: ChainVerification | undefined;
  latestBatch: EvidenceBatch | undefined;
  chainLoading: boolean;
  chainError: string | null;
  onRetryChain: () => void;
  batchesLoading: boolean;
  selectedEventId: string | null;
  onVerifyInclusion: () => void;
  inclusionProof: InclusionProof | undefined;
  inclusionLoading: boolean;
  inclusionEnabled: boolean;
};

export function ChainVerificationPanel({
  chain,
  latestBatch,
  chainLoading,
  chainError,
  onRetryChain,
  batchesLoading,
  selectedEventId,
  onVerifyInclusion,
  inclusionProof,
  inclusionLoading,
  inclusionEnabled,
}: ChainVerificationPanelProps) {
  if (chainLoading || batchesLoading) {
    return (
      <div className="space-y-2" aria-busy>
        <Skeleton height="1rem" />
        <Skeleton height="4rem" />
      </div>
    );
  }

  if (chainError) {
    return <ErrorState message={chainError} onRetry={onRetryChain} />;
  }

  return (
    <div className="space-y-4 text-table">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={
            chain?.is_valid
              ? "rounded-sm bg-ok-bg px-2 py-1 text-sm font-medium text-ok-fg"
              : "rounded-sm bg-risk-bg px-2 py-1 text-sm font-medium text-risk-fg"
          }
        >
          {chain?.is_valid ? "Verified" : "Broken"}
        </span>
        <span className="text-ink-600">
          {chain?.is_valid
            ? `Batches ${chain.first_seq ?? 0}–${chain.last_seq ?? 0} verify against the published root.`
            : chain?.failure_reason}
        </span>
      </div>
      <dl className="grid sm:grid-cols-2 gap-3">
        <div>
          <dt className="text-ink-400">Batch sequence</dt>
          <dd className="tabular-nums font-mono-data">{latestBatch?.seq ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-ink-400">Events in batch</dt>
          <dd className="tabular-nums">{latestBatch?.leaf_count ?? "—"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-ink-400">Merkle root</dt>
          <dd>
            <Digest value={latestBatch?.merkle_root ?? ""} max={40} />
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-ink-400">Previous batch digest</dt>
          <dd>
            {latestBatch?.prev_batch_digest ? (
              <Digest value={latestBatch.prev_batch_digest} max={40} />
            ) : (
              <span className="text-ink-400">Genesis batch</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-ink-400">Batches checked</dt>
          <dd className="tabular-nums">{chain?.batches_checked ?? 0}</dd>
        </div>
        <div>
          <dt className="text-ink-400">Leaves in tree</dt>
          <dd className="tabular-nums">{chain?.tree_size ?? 0}</dd>
        </div>
        {chain?.unsealed_count ? (
          <div className="sm:col-span-2">
            <dt className="text-ink-400">Not yet sealed</dt>
            <dd className="tabular-nums">
              {chain.unsealed_count} event{chain.unsealed_count === 1 ? "" : "s"} recorded since the
              last batch was sealed. These are not covered by the root above.
            </dd>
          </div>
        ) : null}
      </dl>

      <div className="border-t border-line-200 pt-3">
        <button
          type="button"
          className="rounded-sm border border-line-300 bg-bg-sunk px-3 py-2 text-sm font-medium disabled:opacity-40"
          disabled={!inclusionEnabled || !selectedEventId}
          onClick={onVerifyInclusion}
          aria-label="Verify inclusion proof for selected event"
        >
          Verify inclusion proof
        </button>
        {!selectedEventId ? (
          <p className="mt-2 text-xs text-ink-400">Select an event row to verify Merkle inclusion.</p>
        ) : null}
        {inclusionLoading ? <p className="mt-2 text-ink-400">Computing proof…</p> : null}
        {inclusionProof ? (
          <div className="mt-3 rounded-sm bg-bg-sunk p-3">
            <p className="text-sm font-medium text-ink-900">
              Audit path {inclusionProof.is_verified ? "(valid)" : "(invalid)"}
            </p>
            <ol className="mt-2 space-y-1 font-mono-data text-xs">
              {inclusionProof.audit_path.map((step, idx) => (
                <li key={`${idx}-${step.slice(0, 8)}`} className="break-all">
                  {idx + 1}. {step}
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>
    </div>
  );
}
