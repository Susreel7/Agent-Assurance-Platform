import type { ChangeCategory } from "@/api/types";
import { titleCaseSnake } from "@/lib/formatters";

/** Postgres enum order — grouping on release detail must follow this exactly. */
export const CHANGE_CATEGORY_ORDER: readonly ChangeCategory[] = [
  "model",
  "inference_params",
  "prompt",
  "tool",
  "mcp_server",
  "capability",
  "dependency",
  "data_source",
  "data_class",
  "residency",
  "guardrail",
  "oversight",
  "resilience",
  "delegation",
  "deployment",
  "metadata",
  "model_policy",
  "rule_source",
  "rule_obligation",
  "skill",
  "sub_agent",
  "config",
  "memory_retrieval",
] as const;

const CATEGORY_LABEL_OVERRIDES: Partial<Record<ChangeCategory, string>> = {
  mcp_server: "MCP server",
  inference_params: "Inference params",
};

export function changeCategoryLabel(category: ChangeCategory): string {
  return CATEGORY_LABEL_OVERRIDES[category] ?? titleCaseSnake(category);
}
