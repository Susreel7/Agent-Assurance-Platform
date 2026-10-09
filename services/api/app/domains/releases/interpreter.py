"""Deterministic review brief — templates only, never an LLM.

The console's plain-language layer must not be able to hallucinate governance outcomes.
Every sentence is rendered from a ``SemanticChange`` plus named materiality rule ids via
fixed templates, so an auditor can replay the text from structured inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.domains.materiality.rules import describe_rule
from app.domains.releases.schemas import (
    AccreditationImpact,
    ChangeCategory,
    ChangeOperation,
    Materiality,
    ReleaseDiff,
    ReleaseReviewBrief,
    ReviewSentence,
    SemanticChange,
    Severity,
    enforcement_for,
)


def _primary_rule_id(change: SemanticChange) -> str:
    if change.rules_fired:
        return change.rules_fired[0]
    return "REV-000-unclassified"


def _rationale_snippet(rule_id: str) -> str:
    rule = describe_rule(rule_id)
    if rule is None:
        return ""
    sentence = rule.rationale.strip().split(". ")[0]
    if not sentence.endswith("."):
        sentence += "."
    return sentence


def _template_id(change: SemanticChange) -> str:
    cat = change.category.value
    op = change.operation.value
    if change.category is ChangeCategory.TOOL and change.operation is ChangeOperation.ADDED:
        effect = ""
        if isinstance(change.after_value, dict):
            effect = str(change.after_value.get("effect", "unknown"))
        return f"tool.added.{effect or 'unknown'}"
    if change.category is ChangeCategory.MODEL_POLICY and "selection_mode" in change.path:
        return "model_policy.selection_mode"
    if (
        change.category is ChangeCategory.RULE_OBLIGATION
        and change.operation is ChangeOperation.MODIFIED
        and change.path.endswith(".polarity")
    ):
        return "obligation.polarity"
    if change.category is ChangeCategory.SUB_AGENT and change.operation is ChangeOperation.ADDED:
        return "sub_agent.added"
    if change.category is ChangeCategory.MCP_SERVER and change.operation is ChangeOperation.ADDED:
        return "mcp.added"
    if (
        change.category is ChangeCategory.CAPABILITY
        and change.operation is ChangeOperation.ADDED
        and isinstance(change.after_value, dict)
        and change.after_value.get("reversible") is False
    ):
        return "capability.irreversible"
    return f"{cat}.{op}"


def _render_sentence(change: SemanticChange) -> str:
    """Map a structured change to a single reviewer-facing sentence."""
    name = change.subject.strip("'\"")

    if change.category is ChangeCategory.TOOL and change.operation is ChangeOperation.ADDED:
        effect = "unknown"
        if isinstance(change.after_value, dict):
            effect = str(change.after_value.get("effect", "unknown"))
        if effect in ("write", "execute"):
            base = f"This agent gained a tool «{name}» that can modify or run actions ({effect})."
        else:
            base = f"This agent gained a read-only tool «{name}»."
    elif change.category is ChangeCategory.MCP_SERVER and change.operation is ChangeOperation.ADDED:
        url = name
        if isinstance(change.after_value, dict) and change.after_value.get("url"):
            url = str(change.after_value["url"])
        base = f"A new MCP server «{url}» was attached, expanding tools available to the agent."
    elif (
        change.category is ChangeCategory.MODEL_POLICY
        and change.path.endswith("selection_mode")
        and str(change.after_value) == "auto"
    ):
        base = (
            "Model selection changed to automatic routing; production data may reach "
            "models not listed in the descriptor."
        )
    elif change.category is ChangeCategory.RULE_OBLIGATION and change.path.endswith(".polarity"):
        base = (
            f"A rule obligation ({name}) changed polarity from "
            f"{change.before_value!s} to {change.after_value!s}."
        )
    elif change.category is ChangeCategory.SUB_AGENT and change.operation is ChangeOperation.ADDED:
        base = f"This agent may delegate work to a new sub-agent «{name}»."
    elif change.operation is ChangeOperation.RENAMED:
        base = change.summary.rstrip(".") + "."
    elif change.category is ChangeCategory.CAPABILITY and change.operation is ChangeOperation.ADDED:
        base = f"This agent gained a new capability: «{name}»."
    else:
        base = change.summary.rstrip(".") + "."

    rule_id = _primary_rule_id(change)
    snippet = _rationale_snippet(rule_id)
    text = f"{base} {snippet}".strip() if snippet else base
    return text[:512]


def sentence_from_change(change: SemanticChange) -> ReviewSentence:
    rule_ids = change.rules_fired or ("REV-000-unclassified",)
    return ReviewSentence(
        change_path=change.path,
        rule_ids=tuple(rule_ids),
        template_id=_template_id(change),
        text=_render_sentence(change),
        severity=change.severity,
        materiality=change.verdict,
        enforcement=enforcement_for(change.verdict),
    )


def build_review_brief(
    diff: ReleaseDiff,
    *,
    descriptor_digest: str,
    release_id: UUID | None = None,
    generated_at: datetime | None = None,
) -> ReleaseReviewBrief:
    """Group deterministic sentences — re-accreditation first, then review, then the rest."""
    when = generated_at or datetime.now(UTC)
    re_accreditation: list[ReviewSentence] = []
    needs_review: list[ReviewSentence] = []
    informational: list[ReviewSentence] = []
    blocking_rules: list[str] = []

    for change in diff.changes:
        sentence = sentence_from_change(change)
        if change.verdict is Materiality.MATERIAL:
            re_accreditation.append(sentence)
            for rule_id in change.rules_fired:
                if rule_id.startswith("MAT-"):
                    blocking_rules.append(rule_id)
        elif change.verdict is Materiality.NEEDS_REVIEW:
            needs_review.append(sentence)
        else:
            informational.append(sentence)

    def _severity_rank(sev: Severity) -> int:
        order = (
            Severity.CRITICAL,
            Severity.HIGH,
            Severity.MEDIUM,
            Severity.LOW,
            Severity.INFO,
        )
        return order.index(sev)

    def _sort_key(s: ReviewSentence) -> tuple[int, str]:
        return (-_severity_rank(s.severity), s.change_path)

    re_accreditation.sort(key=_sort_key)
    needs_review.sort(key=_sort_key)
    informational.sort(key=_sort_key)

    impact = diff.accreditation_impact
    headline = diff.headline()
    if impact is AccreditationImpact.SUSPENDS:
        headline = f"Re-accreditation required — {headline}"
    elif impact is AccreditationImpact.REQUIRES_REVALIDATION:
        headline = f"Review required before approval — {headline}"

    seen: dict[str, None] = {}
    for rid in blocking_rules:
        seen.setdefault(rid, None)

    return ReleaseReviewBrief(
        release_id=release_id,
        from_semver=diff.from_semver,
        to_semver=diff.to_semver,
        descriptor_digest=descriptor_digest,
        headline=headline,
        re_accreditation=re_accreditation,
        needs_review=needs_review,
        informational=informational,
        accreditation_impact=impact,
        blocking_rule_ids=list(seen),
        generated_at=when,
    )


def brief_paths(brief: ReleaseReviewBrief) -> set[str]:
    paths: set[str] = set()
    for bucket in (brief.re_accreditation, brief.needs_review, brief.informational):
        for sentence in bucket:
            paths.add(sentence.change_path)
    return paths
