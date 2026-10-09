import type { ReactNode } from "react";

type Props = {
  title: string;
  /**
   * One sentence, in plain English, saying what this screen is for.
   *
   * Required rather than optional on purpose. Every screen in this product shows a
   * concept the reader may not have met — accreditation, materiality, evidence chains —
   * and a heading that only names the concept explains nothing to someone who does not
   * already know it. If a screen cannot be described in one sentence, that is a problem
   * with the screen.
   */
  explain: string;
  /** Optional right-hand actions: filters, buttons, a link out. */
  actions?: ReactNode;
};

export function PageHeader({ title, explain, actions }: Props) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4 pb-5">
      <div className="max-w-2xl">
        <h1 className="text-display font-bold tracking-tight text-ink-900">{title}</h1>
        <p className="mt-1.5 text-lede text-ink-600">{explain}</p>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}
