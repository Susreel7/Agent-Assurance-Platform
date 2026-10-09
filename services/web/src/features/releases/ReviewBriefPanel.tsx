import type { ReleaseReviewBrief, ReviewSentence } from "@/api/types";
import { Panel } from "@/components/Panel";

function BriefSection({
  title,
  tone,
  sentences,
  onSelectChange,
}: {
  title: string;
  tone: "critical" | "warn" | "muted";
  sentences: ReviewSentence[];
  onSelectChange?: (path: string) => void;
}) {
  if (sentences.length === 0) return null;
  const border =
    tone === "critical"
      ? "border-l-accent"
      : tone === "warn"
        ? "border-l-amber-500"
        : "border-l-line-200";
  return (
    <section className="mb-4 last:mb-0">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600 mb-2">{title}</h3>
      <ul className="space-y-2">
        {sentences.map((s) => (
          <li
            key={`${s.change_path}-${s.template_id}`}
            className={`rounded-md border border-line-200 bg-bg-panel px-3 py-2 text-table text-ink-800 border-l-4 ${border}`}
          >
            <p>{s.text}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-500">
              <span className="rounded bg-bg-sunk px-1.5 py-0.5 font-mono-data uppercase">{s.severity}</span>
              <span className="rounded bg-bg-sunk px-1.5 py-0.5">{s.enforcement}</span>
              {s.rule_ids[0] ? (
                <span className="font-mono-data truncate max-w-[12rem]" title={s.rule_ids.join(", ")}>
                  {s.rule_ids[0]}
                </span>
              ) : null}
              {onSelectChange ? (
                <button
                  type="button"
                  className="text-accent-ink hover:underline"
                  onClick={() => onSelectChange(s.change_path)}
                >
                  View change
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

type Props = {
  brief: ReleaseReviewBrief;
  onSelectChange?: (path: string) => void;
};

export function ReviewBriefPanel({ brief, onSelectChange }: Props) {
  return (
    <Panel title="Review brief" noPadding>
      <div className="px-4 py-3 space-y-1 border-b border-line-200 bg-bg-sunk">
        <p className="text-sm font-medium text-ink-900">{brief.headline}</p>
        <p className="text-xs text-ink-500 font-mono-data truncate" title={brief.descriptor_digest}>
          Descriptor digest {brief.descriptor_digest.slice(0, 18)}…
        </p>
        <p className="text-xs text-ink-400">
          Plain-language summary from deterministic templates ({brief.generator_label}). Not AI-generated.
        </p>
      </div>
      <div className="px-4 py-3">
        <BriefSection
          title="Requires re-accreditation"
          tone="critical"
          sentences={brief.re_accreditation}
          onSelectChange={onSelectChange}
        />
        <BriefSection
          title="Needs your review"
          tone="warn"
          sentences={brief.needs_review}
          onSelectChange={onSelectChange}
        />
        <BriefSection
          title="Recorded for awareness"
          tone="muted"
          sentences={brief.informational}
          onSelectChange={onSelectChange}
        />
        {brief.re_accreditation.length === 0 &&
        brief.needs_review.length === 0 &&
        brief.informational.length === 0 ? (
          <p className="text-table text-ink-400 py-4 text-center">No governed changes to summarise.</p>
        ) : null}
      </div>
    </Panel>
  );
}
