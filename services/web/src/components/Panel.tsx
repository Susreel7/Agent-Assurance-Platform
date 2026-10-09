/**
 * The container every block of content sits in.
 *
 * One card style for the whole console. Panels that vary their border, radius or
 * shadow by importance produce a page where the eye has to rank five things before
 * reading any of them, and the ranking is almost never the one the author intended.
 *
 * `explain` is the small grey line under a panel title. It is optional here, unlike on
 * PageHeader, because a panel inside an explained screen usually inherits its context —
 * but a panel showing a term from this product's own vocabulary should always use it.
 */

import clsx from "clsx";
import { Link } from "react-router-dom";

type PanelProps = {
  title?: string;
  explain?: string;
  toolbar?: React.ReactNode;
  /** A single "see all" style link, rendered at the right of the header. */
  more?: { label: string; to: string };
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  noPadding?: boolean;
};

export function Panel({
  title,
  explain,
  toolbar,
  more,
  children,
  footer,
  className,
  noPadding,
}: PanelProps) {
  const hasHeader = Boolean(title || toolbar || more);

  return (
    <section className={clsx("glass-card flex flex-col rounded-card", className)}>
      {hasHeader ? (
        <header className="flex items-start justify-between gap-4 px-4 pb-3 pt-3.5">
          <div className="min-w-0">
            {title ? (
              <h2 className="text-body font-semibold tracking-tight text-ink-900">{title}</h2>
            ) : null}
            {explain ? <p className="mt-0.5 text-micro text-ink-400">{explain}</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {toolbar}
            {more ? (
              <Link
                to={more.to}
                className="text-table font-medium text-accent-ink hover:underline"
              >
                {more.label}
              </Link>
            ) : null}
          </div>
        </header>
      ) : null}

      <div className={clsx("min-w-0 flex-1", noPadding ? undefined : "px-4 pb-4", !hasHeader && !noPadding && "pt-4")}>
        {children}
      </div>

      {footer ? (
        <footer className="border-t border-line-200 px-4 py-2.5 text-micro text-ink-400">
          {footer}
        </footer>
      ) : null}
    </section>
  );
}
