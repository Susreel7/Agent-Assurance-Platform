/**
 * Types for `lucide-react`'s per-icon entry points.
 *
 * The package ships one declaration file for the barrel and none for the ~1,600 icon
 * modules underneath it, so `import Radar from "lucide-react/dist/esm/icons/radar"` is
 * correct at runtime and an implicit `any` to TypeScript. That is the entire reason
 * people keep the barrel import: it is the only one that type-checks.
 *
 * `import type` is erased, so naming `LucideIcon` here costs nothing at runtime — the
 * bundle still pulls in one icon module per import and never the index. This file is
 * what makes `inv_no_lucide_barrel` a rule someone can follow rather than a rule that
 * trades types for bundle size.
 */

declare module "lucide-react/dist/esm/icons/*" {
  import type { LucideIcon } from "lucide-react";

  const Icon: LucideIcon;
  export default Icon;
}
