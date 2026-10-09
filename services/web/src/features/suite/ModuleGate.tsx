/**
 * Whether a licensed module may be opened at all.
 *
 * Distinct from navigation, which already hides what the caller cannot use: this is the
 * deep link. Somebody pastes a URL into Slack, the recipient's install does not have the
 * module, and the answer has to be a sentence rather than an empty screen.
 *
 * The entitlement itself comes from the bootstrap. Refetching `/v1/modules` here was a
 * second request for an answer the shell already had, and it arrived after first paint,
 * so the gate flashed a skeleton over a page that was never going to render.
 */

import type { ReactNode } from "react";
import type { SuiteModuleId } from "@/api/types";
import { canReadModule, isModuleLicensed } from "@/lib/suiteModules";
import { EmptyState } from "@/components/EmptyState";
import { useIdentity } from "@/features/auth/bootstrapContext";

const LABELS: Record<SuiteModuleId, string> = {
  router: "Router",
  observe: "Observe",
  prompt: "Prompt",
  evaluate: "Evaluate",
};

type ModuleGateProps = {
  moduleId: SuiteModuleId;
  children: ReactNode;
};

export function ModuleGate({ moduleId, children }: ModuleGateProps) {
  const manifest = useIdentity().modules;

  if (!isModuleLicensed(manifest, moduleId)) {
    return (
      <EmptyState
        title={`${LABELS[moduleId]} is not included in this licence`}
        description="This module is not enabled on this install. An account owner can add it to the suite entitlement."
      />
    );
  }

  if (!canReadModule(manifest, moduleId)) {
    return (
      <EmptyState
        title={`${LABELS[moduleId]} is read-disabled`}
        description="The licence covers this module but read access is switched off, which usually means the entitlement has expired."
      />
    );
  }

  return <>{children}</>;
}
