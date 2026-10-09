/** Holds the shared time window. See lib/windowDays.ts for why there is only one. */

import { useCallback, useMemo, useState } from "react";
import {
  WINDOW_STORAGE_KEY,
  WindowDaysContext,
  readStoredWindow,
  type WindowDays,
} from "@/lib/windowDays";

export function WindowDaysProvider({ children }: { children: React.ReactNode }) {
  const [days, setDaysState] = useState<WindowDays>(readStoredWindow);

  const setDays = useCallback((next: WindowDays) => {
    setDaysState(next);
    try {
      window.localStorage.setItem(WINDOW_STORAGE_KEY, String(next));
    } catch {
      // Private browsing. The choice still applies for this session.
    }
  }, []);

  const value = useMemo(() => ({ days, setDays }), [days, setDays]);
  return <WindowDaysContext.Provider value={value}>{children}</WindowDaysContext.Provider>;
}
