/** Holds the theme choice. See lib/theme.ts for why the flash-free part lives in HTML. */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  DARK_QUERY,
  THEME_STORAGE_KEY,
  ThemeContext,
  applyToDocument,
  readStoredChoice,
  systemPrefersDark,
  type ResolvedTheme,
  type ThemeChoice,
} from "@/lib/theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Lazy initialisers: both of these touch synchronous browser APIs, which would otherwise
  // run on every render of this provider.
  const [choice, setChoiceState] = useState<ThemeChoice>(readStoredChoice);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  // Derived during render rather than held in state. Storing it would mean an effect that
  // sets state in response to a prop change, which costs an extra render and can drift out
  // of step with `choice` for a frame.
  const resolved: ResolvedTheme = choice === "system" ? (systemDark ? "dark" : "light") : choice;

  useEffect(() => {
    applyToDocument(resolved);
  }, [resolved]);

  useEffect(() => {
    // Only `system` follows the OS. Subscribing unconditionally would make an explicit
    // choice silently change at sunset, which is the opposite of choosing.
    if (choice !== "system") return;

    const media = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [choice]);

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Private browsing. The choice still applies for this session.
    }
  }, []);

  const value = useMemo(() => ({ choice, resolved, setChoice }), [choice, resolved, setChoice]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
