/**
 * How far back every operational screen is looking.
 *
 * One setting, in the top bar, shared by the dashboard, runs, cost and tools. Giving
 * each screen its own range picker sounds more flexible and is worse in practice: you
 * compare a cost figure from one screen against a run count from another and they were
 * measured over different weeks, with nothing on either page saying so.
 *
 * Persisted, because the window someone picks is a habit rather than a decision — an
 * ops lead lives on 7 days and a finance reviewer lives on 90, and neither wants to set
 * it again every morning.
 *
 * The provider component lives in components/WindowDaysProvider.tsx. Splitting it out
 * keeps this file free of component exports, which is what lets Vite hot-reload a
 * screen without remounting the whole tree and losing the state it was showing.
 */

import { createContext, useContext } from "react";

export const WINDOW_CHOICES = [7, 30, 90] as const;
export type WindowDays = (typeof WINDOW_CHOICES)[number];

export const WINDOW_STORAGE_KEY = "aap.windowDays";
export const DEFAULT_WINDOW: WindowDays = 30;

export function readStoredWindow(): WindowDays {
  try {
    const stored = Number(window.localStorage.getItem(WINDOW_STORAGE_KEY));
    return (WINDOW_CHOICES as readonly number[]).includes(stored)
      ? (stored as WindowDays)
      : DEFAULT_WINDOW;
  } catch {
    return DEFAULT_WINDOW;
  }
}

export type WindowContextValue = { days: WindowDays; setDays: (days: WindowDays) => void };

export const WindowDaysContext = createContext<WindowContextValue>({
  days: DEFAULT_WINDOW,
  setDays: () => {},
});

export function useWindowDays(): WindowContextValue {
  return useContext(WindowDaysContext);
}

export function windowLabel(days: number): string {
  if (days === 1) return "Today";
  if (days % 30 === 0 && days >= 30) return `Last ${days / 30} month${days === 30 ? "" : "s"}`;
  return `Last ${days} days`;
}
