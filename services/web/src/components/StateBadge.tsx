import clsx from "clsx";
import type {
  AccreditationState,
  AgentHealth,
  FindingState,
  LifecycleState,
  Materiality,
  ReleaseState,
  RunOutcome,
  Severity,
} from "@/api/types";
import { materialityLabel } from "@/lib/materiality";
import { titleCaseSnake } from "@/lib/formatters";

type BadgeTone = "ok" | "warn" | "risk" | "info" | "mute";

const toneClass: Record<BadgeTone, string> = {
  ok: "bg-ok-bg text-ok-fg",
  warn: "bg-warn-bg text-warn-fg",
  risk: "bg-risk-bg text-risk-fg",
  info: "bg-info-bg text-info-fg",
  mute: "bg-mute-bg text-mute-fg",
};

export function Badge({ label, tone }: { label: string; tone: BadgeTone }) {
  return (
    <span className={clsx("inline-flex items-center rounded px-1.5 py-0.5 text-micro font-medium", toneClass[tone])}>
      {label}
    </span>
  );
}

/**
 * How an agent is doing, in one word.
 *
 * "At risk" and "critical" are both red, in different weights, because the difference
 * between them is urgency rather than kind — and giving urgency its own hue would mean
 * inventing a colour that means "quite bad".
 */
export function HealthBadge({ health }: { health: AgentHealth }) {
  const tone: BadgeTone =
    health === "healthy" ? "ok" : health === "warning" ? "warn" : "risk";
  const label = health === "at_risk" ? "At risk" : titleCaseSnake(health);
  return <Badge label={label} tone={tone} />;
}

/**
 * How a run ended.
 *
 * `refused` is deliberately not red. An agent declining to act because a guardrail
 * fired is the system working, and colouring it as a failure is how somebody ends up
 * arguing for turning the guardrail off.
 */
export function RunOutcomeBadge({ outcome }: { outcome: RunOutcome }) {
  const tone: BadgeTone =
    outcome === "succeeded"
      ? "ok"
      : outcome === "failed" || outcome === "timed_out"
        ? "risk"
        : outcome === "refused"
          ? "info"
          : outcome === "running"
            ? "warn"
            : "mute";
  return <Badge label={titleCaseSnake(outcome)} tone={tone} />;
}

/** LangGraph, the Cursor SDK, CrewAI. Neutral by design: no framework is a problem. */
export function FrameworkTag({ framework }: { framework: string | null }) {
  if (!framework) return <span className="text-micro text-ink-300">—</span>;
  return (
    <span className="inline-flex items-center rounded border border-line-200 bg-bg-sunk px-1.5 py-0.5 text-micro text-ink-600">
      {framework}
    </span>
  );
}

/** Accepts a plain string as well as the enum, because one endpoint returns one.
 *
 * The materiality assessment selects `state::text`, so its accreditation state arrives
 * untyped. The tone logic below already falls through to "mute" for anything it does not
 * recognise, so widening the parameter costs nothing and beats the alternatives: casting
 * at the call site asserts something unchecked, and mapping an unknown state onto a known
 * one would invent data.
 */
export function AccreditationStateBadge({ state }: { state: AccreditationState | string }) {
  const tone: BadgeTone =
    state === "approved"
      ? "ok"
      : state === "suspended" || state === "expired"
        ? "risk"
        : state === "submitted"
          ? "info"
          : "mute";
  return <Badge label={titleCaseSnake(state)} tone={tone} />;
}

export function ReleaseStateBadge({ state }: { state: ReleaseState }) {
  const tone: BadgeTone =
    state === "rolled_out" || state === "approved"
      ? "ok"
      : state === "proposed"
        ? "info"
        : state === "rolled_back" || state === "abandoned"
          ? "risk"
          : "mute";
  return <Badge label={titleCaseSnake(state)} tone={tone} />;
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const tone: BadgeTone =
    severity === "critical" || severity === "high"
      ? "risk"
      : severity === "medium"
        ? "warn"
        : severity === "info"
          ? "info"
          : "mute";
  return <Badge label={titleCaseSnake(severity)} tone={tone} />;
}

export function MaterialityBadge({ verdict }: { verdict: Materiality }) {
  const tone: BadgeTone =
    verdict === "material" ? "risk" : verdict === "needs_review" ? "warn" : "ok";
  return <Badge label={materialityLabel(verdict)} tone={tone} />;
}

export function LifecycleStateBadge({ state }: { state: LifecycleState }) {
  const tone: BadgeTone = state === "production" ? "ok" : state === "retired" ? "mute" : "info";
  return <Badge label={titleCaseSnake(state)} tone={tone} />;
}

export function FindingStateBadge({ state }: { state: FindingState }) {
  // `open` and `triaged` are both still open work — triaged only means somebody has
  // looked. Only `fixed` and `mitigated` are green.
  const tone: BadgeTone =
    state === "fixed" || state === "mitigated"
      ? "ok"
      : state === "open" || state === "triaged"
        ? "warn"
        : state === "false_positive"
          ? "mute"
          : "info";
  return <Badge label={titleCaseSnake(state)} tone={tone} />;
}

export function StateBadge(props: {
  kind: "accreditation" | "release" | "severity" | "materiality" | "lifecycle" | "finding";
  value: AccreditationState | ReleaseState | Severity | Materiality | LifecycleState | FindingState;
}) {
  switch (props.kind) {
    case "accreditation":
      return <AccreditationStateBadge state={props.value as AccreditationState} />;
    case "release":
      return <ReleaseStateBadge state={props.value as ReleaseState} />;
    case "severity":
      return <SeverityBadge severity={props.value as Severity} />;
    case "materiality":
      return <MaterialityBadge verdict={props.value as Materiality} />;
    case "lifecycle":
      return <LifecycleStateBadge state={props.value as LifecycleState} />;
    case "finding":
      return <FindingStateBadge state={props.value as FindingState} />;
    default:
      return null;
  }
}
