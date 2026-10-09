/**
 * One number, what it means, and whether it is moving.
 */

import clsx from "clsx";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "./Icon";
import { Sparkline } from "./charts/Sparkline";

export type StatTone = "neutral" | "ok" | "warn" | "risk";

type StatProps = {
  label: string;
  value: string;
  explain?: string;
  tone?: StatTone;
  icon?: IconName;
  iconTint?: "accent" | "ok" | "warn" | "risk" | "info";
  delta?: { pct: number; upIsGood: boolean; caption?: string };
  sparkline?: number[];
  href?: string;
  children?: React.ReactNode;
};

const VALUE_TONE: Record<StatTone, string> = {
  neutral: "text-ink-900",
  ok: "text-ok-fg",
  warn: "text-warn-fg",
  risk: "text-risk-fg",
};

const ICON_TINT: Record<NonNullable<StatProps["iconTint"]>, string> = {
  accent: "bg-accent-soft text-accent-ink",
  ok: "bg-ok-bg text-ok-fg",
  warn: "bg-warn-bg text-warn-fg",
  risk: "bg-risk-bg text-risk-fg",
  info: "bg-info-bg text-info-fg",
};

function Delta({ pct, upIsGood, caption }: { pct: number; upIsGood: boolean; caption?: string }) {
  if (!Number.isFinite(pct) || Math.abs(pct) < 0.5) {
    return caption ? <span className="text-micro text-ink-400">{caption}</span> : null;
  }
  const up = pct > 0;
  const good = up === upIsGood;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-0.5 text-micro font-medium",
        good ? "text-ok-fg" : "text-risk-fg",
      )}
    >
      <Icon name={up ? "arrowUp" : "arrowDown"} size={12} />
      {up ? "+" : "−"}
      {Math.abs(pct).toFixed(Math.abs(pct) >= 10 ? 0 : 1)}% {caption ?? "vs prior period"}
    </span>
  );
}

export function Stat({
  label,
  value,
  explain,
  tone = "neutral",
  icon,
  iconTint = "accent",
  delta,
  sparkline,
  href,
  children,
}: StatProps) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {icon ? (
            <span
              className={clsx(
                "mb-2.5 inline-flex h-9 w-9 items-center justify-center rounded-lg",
                ICON_TINT[iconTint],
              )}
            >
              <Icon name={icon} size={18} />
            </span>
          ) : null}
          <p className="text-micro font-medium text-ink-600">{label}</p>
          <div className="mt-1 flex items-end justify-between gap-2">
            <p className={clsx("font-semibold tabular-nums text-stat", VALUE_TONE[tone])}>{value}</p>
            {sparkline && sparkline.length > 1 ? (
              <Sparkline values={sparkline} color={tone === "risk" ? "var(--risk-solid)" : "var(--accent)"} />
            ) : null}
          </div>
          {delta ? (
            <p className="mt-1">
              <Delta {...delta} />
            </p>
          ) : explain ? (
            <p className="mt-1 text-micro text-ink-400">{explain}</p>
          ) : null}
        </div>
      </div>
      {children ? <div className="mt-2.5">{children}</div> : null}
    </>
  );

  // Only the linked variant lifts on hover. A card that moves under the cursor without
  // being clickable reads as an affordance that does nothing.
  const shell = clsx("glass-card block rounded-card px-4 py-4", href && "glass-card-hover");

  return href ? (
    <Link to={href} className={clsx(shell, "hover:no-underline")}>
      {body}
    </Link>
  ) : (
    <div className={shell}>{body}</div>
  );
}
