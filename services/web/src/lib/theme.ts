/**
 * Theme selection, and the small amount of care it takes to do without a flash.
 *
 * The chosen theme lives in localStorage, which React cannot read before it mounts. A
 * provider that read it in an effect would paint the default theme first and correct itself
 * a frame later — on a dark-by-default console that is a white flash on every navigation to
 * a fresh document. The class is therefore applied by a synchronous script in `index.html`
 * before the first paint, and this module's job is to stay consistent with what that script
 * already decided rather than to decide it again.
 *
 * `system` is a real third state, not a computed initial value. Someone who picks it is
 * asking to follow the operating system from then on, including when it changes at sunset.
 *
 * The provider component lives in components/ThemeProvider.tsx. Splitting it out keeps this
 * file free of component exports, which is what lets Vite hot-reload a screen without
 * remounting the whole tree — the same reason lib/windowDays.ts is arranged this way.
 */

import { createContext, useContext } from "react";

export type ThemeChoice = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

/** Shared with the inline script in `index.html`. Changing it here changes it there. */
export const THEME_STORAGE_KEY = "aap.theme.v1";

export const DARK_QUERY = "(prefers-color-scheme: dark)";

export function readStoredChoice(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "dark" || stored === "light" || stored === "system") return stored;
  } catch {
    // Throws in private browsing and when storage is disabled. A theme is not worth
    // failing a page load over.
  }
  return "dark";
}

export function systemPrefersDark(): boolean {
  try {
    return window.matchMedia(DARK_QUERY).matches;
  } catch {
    return true;
  }
}

export function applyToDocument(resolved: ResolvedTheme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.classList.toggle("light", resolved === "light");
}

export type ThemeContextValue = {
  /** What the operator picked, including `system`. */
  choice: ThemeChoice;
  /** What is actually on the page right now. Never `system`. */
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice) => void;
};

export const ThemeContext = createContext<ThemeContextValue>({
  choice: "dark",
  resolved: "dark",
  setChoice: () => {},
});

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
