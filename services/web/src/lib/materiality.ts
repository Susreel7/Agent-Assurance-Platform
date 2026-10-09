import type { AccreditationImpact, Materiality } from "@/api/types";

export function materialityLabel(verdict: Materiality): string {
  const map: Record<Materiality, string> = {
    material: "Material",
    immaterial: "Immaterial",
    needs_review: "Needs review",
  };
  return map[verdict];
}

export function accreditationImpactLabel(impact: AccreditationImpact): string {
  const map: Record<AccreditationImpact, string> = {
    none: "Approval stands",
    requires_revalidation: "Revalidation required",
    suspends: "Approval suspended",
  };
  return map[impact];
}

export function accreditationImpactTone(impact: AccreditationImpact): "ok" | "warn" | "risk" {
  if (impact === "none") return "ok";
  if (impact === "requires_revalidation") return "warn";
  return "risk";
}
