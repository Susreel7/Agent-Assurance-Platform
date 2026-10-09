/**
 * The bootstrap response, shared by everything inside the shell.
 *
 * Separate from `AuthGate.tsx` so that a component importing the context does not pull
 * in the gate, and so Vite's fast refresh keeps working — a module that exports both a
 * component and a non-component loses it.
 *
 * The context is only ever populated by `AuthGate`, which renders nothing until the
 * request has resolved. `useIdentity` therefore never has to handle "not loaded yet",
 * which is the state every consumer used to have to write a branch for.
 */

import { createContext, useContext } from "react";
import type { Bootstrap, CapabilityFlag, ProductMode } from "./useBootstrap";

export const BootstrapContext = createContext<Bootstrap | null>(null);

export function useIdentity(): Bootstrap {
  const value = useContext(BootstrapContext);
  if (value === null) {
    throw new Error("useIdentity must be used inside <AuthGate>");
  }
  return value;
}

/** True when this member holds `permission` anywhere. */
export function usePermission(permission: string): boolean {
  return useIdentity().access.permissions.includes(permission);
}

/**
 * Which product this console leads with.
 *
 * Read this instead of branching on a route or a licence. Two screens asking the same
 * question two different ways is how the console ended up with two navigations that
 * disagreed about which product was primary.
 */
export function useProductMode(): ProductMode {
  return useIdentity().product_mode;
}

/**
 * Whether an optional surface is switched on for this install.
 *
 * Only ever used to decide whether to *offer* something. A route guarded by this would
 * turn a bookmark into a dead end, and the screens behind these flags all still work.
 */
export function useCapabilityFlag(flag: CapabilityFlag): boolean {
  return useIdentity().capability_flags[flag] === true;
}
