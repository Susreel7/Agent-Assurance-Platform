import type { ModulesManifest, SuiteModuleId, SuiteModuleOut } from "@/api/types";

export const SUITE_MODULE_IDS = ["router", "observe", "prompt", "evaluate"] as const;

export function moduleEntry(
  manifest: ModulesManifest | undefined,
  id: SuiteModuleId,
): SuiteModuleOut | undefined {
  return manifest?.modules[id];
}

export function isModuleLicensed(
  manifest: ModulesManifest | undefined,
  id: SuiteModuleId,
): boolean {
  const entry = moduleEntry(manifest, id);
  return Boolean(entry?.enabled);
}

export function canReadModule(
  manifest: ModulesManifest | undefined,
  id: SuiteModuleId,
): boolean {
  const entry = moduleEntry(manifest, id);
  return Boolean(entry?.enabled && entry.access.read);
}

export function canConfigureModule(
  manifest: ModulesManifest | undefined,
  id: SuiteModuleId,
): boolean {
  const entry = moduleEntry(manifest, id);
  return Boolean(entry?.enabled && entry.access.configure);
}
