import type { ElementType, ReactNode } from "react";
import { clsx } from "clsx";

export function NexusCard({
  children,
  className,
  pad = false,
}: {
  children: ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <div
      className={clsx(
        "glass-card flex flex-col overflow-hidden rounded-2xl",
        pad && "p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function NexusBadge({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "ok" | "warn" | "risk" | "info" | "default";
}) {
  const tones = {
    ok: "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    warn: "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-400",
    risk: "border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-400",
    info: "border-blue-500/25 bg-blue-500/10 text-blue-700 dark:text-blue-400",
    default:
      "border-slate-300 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-white/5 dark:text-slate-300",
  };
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        tones[tone],
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}

export function NexusMetric({
  label,
  value,
  meta,
  tone = "default",
}: {
  label: string;
  value: string;
  meta: string;
  tone?: "positive" | "negative" | "default";
}) {
  return (
    <NexusCard pad>
      <div className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-400">{label}</div>
      <div
        className={clsx(
          "mb-1 text-3xl font-bold tracking-tight",
          tone === "positive"
            ? "text-emerald-600 dark:text-emerald-400"
            : tone === "negative"
              ? "text-rose-600 dark:text-rose-400"
              : "text-slate-900 dark:text-white",
        )}
      >
        {value}
      </div>
      <div className="text-xs text-slate-500">{meta}</div>
    </NexusCard>
  );
}

export function NexusPageHeader({
  crumbs,
  title,
  lede,
  actions,
}: {
  crumbs: string[];
  title: string;
  lede: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 animate-fade-rise">
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium text-slate-500">
        {crumbs.map((crumb, index) => (
          <span key={crumb} className="contents">
            {index > 0 ? <span className="text-slate-400 dark:text-slate-600">/</span> : null}
            <span
              className={
                index === crumbs.length - 1
                  ? "font-semibold text-slate-800 dark:text-slate-300"
                  : ""
              }
            >
              {crumb}
            </span>
          </span>
        ))}
      </div>
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div>
          <h1 className="mb-2 text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
            {title}
          </h1>
          <p className="max-w-3xl text-sm text-slate-600 dark:text-slate-400">{lede}</p>
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

export function NexusAttention({
  icon: Icon,
  title,
  detail,
  tone,
}: {
  icon: ElementType;
  title: string;
  detail: string;
  tone: "risk" | "warn" | "info";
}) {
  const tint = {
    risk: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
    warn: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    info: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  };
  return (
    <div className="group flex items-start gap-4 border-b border-slate-200 py-3 last:border-0 dark:border-white/5">
      <span
        className={clsx(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          tint[tone],
        )}
      >
        <Icon size={16} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-slate-800 group-hover:text-indigo-600 dark:text-slate-200 dark:group-hover:text-white">
          {title}
        </span>
        <span className="mt-1 block truncate text-xs text-slate-500 dark:text-slate-400">
          {detail}
        </span>
      </span>
    </div>
  );
}
