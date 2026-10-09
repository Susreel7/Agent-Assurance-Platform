/**
 * Shared time-window control — used in the top bar and on the overview greeting row.
 */

import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Icon } from "./Icon";
import { WINDOW_CHOICES, useWindowDays, windowLabel } from "@/lib/windowDays";

type Props = {
  variant?: "compact" | "card";
  className?: string;
};

export function WindowDaysSelect({ variant = "compact", className }: Props) {
  const { days, setDays } = useWindowDays();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  if (variant === "compact") {
    return (
      <div
        className={clsx("flex items-center rounded-lg bg-bg-sunk p-0.5", className)}
        role="group"
        aria-label="Time window"
      >
        {WINDOW_CHOICES.map((choice) => (
          <button
            key={choice}
            type="button"
            onClick={() => setDays(choice)}
            aria-pressed={days === choice}
            title={windowLabel(choice)}
            className={clsx(
              "rounded-md px-2.5 py-1 text-table transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
              days === choice
                ? "bg-bg-panel font-medium text-ink-900 shadow-hairline"
                : "text-ink-600 hover:text-ink-900",
            )}
          >
            {choice}d
          </button>
        ))}
      </div>
    );
  }

  return (
    <div ref={ref} className={clsx("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        className="flex items-center gap-2 rounded-card border border-line-200 bg-bg-panel px-3 py-2 text-table text-ink-700 shadow-hairline transition-colors hover:bg-bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <Icon name="calendar" size={16} className="text-ink-400" />
        <span>{windowLabel(days)}</span>
        <Icon name="chevronDown" size={14} className="text-ink-400" />
      </button>
      {open ? (
        <ul
          role="listbox"
          aria-label="Time window"
          className="absolute right-0 top-full z-30 mt-1.5 min-w-[10rem] animate-fade-rise overflow-hidden rounded-card border border-line-200 bg-bg-panel py-1 shadow-pop"
        >
          {WINDOW_CHOICES.map((choice) => (
            <li key={choice}>
              <button
                type="button"
                role="option"
                aria-selected={days === choice}
                onClick={() => {
                  setDays(choice);
                  setOpen(false);
                }}
                className={clsx(
                  "flex w-full px-3 py-2 text-left text-table",
                  days === choice ? "bg-bg-hover font-medium text-ink-900" : "text-ink-600 hover:bg-bg-hover",
                )}
              >
                {windowLabel(choice)}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
