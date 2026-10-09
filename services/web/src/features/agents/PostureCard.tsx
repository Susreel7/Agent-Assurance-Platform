import type { PostureScore } from "@/api/types";

type PostureCardProps = {
  posture: PostureScore;
};

export function PostureCard({ posture }: PostureCardProps) {
  return (
    <section className="rounded-sm border border-line-200 bg-bg-sunk p-4">
      <div className="flex items-baseline gap-3">
        <p className="text-3xl font-semibold tabular-nums text-ink-900">{posture.score}</p>
        <p className="text-sm text-ink-600">Posture score</p>
      </div>
      <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-600">
        Contributing factors
      </h3>
      <ul className="mt-2 space-y-2">
        {posture.contributors.map((c) => (
          <li key={c.factor} className="text-table">
            <div className="flex justify-between gap-2">
              <span className="text-ink-900">{c.factor}</span>
              <span className="tabular-nums text-ink-600">−{c.weight}</span>
            </div>
            <p className="text-ink-400">{c.detail}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
