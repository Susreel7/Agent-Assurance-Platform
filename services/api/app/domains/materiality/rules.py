"""The materiality rule set — HLD page 5, made executable.

A third sanctioned file in this domain beyond the four in AGENTS.md, for the same
reason as ``releases/differ.py``: pure computation, no database, no HTTP, and the file
most worth reading in isolation.

This is the defensible part of the product. Observability vendors can tell you what an
agent did. Security vendors can block what it is about to do. Identity vendors can tell
you it exists. None of them hold the approved **baseline**, so none of them can answer
the question a reviewer actually asks: *is this still the thing we signed off on?*

Three properties matter more than the rule list itself.

**Every verdict names the rule that produced it.** A change marked material without a
rule id is unusable: the owner cannot argue with it, the reviewer cannot audit it, and
nobody can tune it. ``rules_fired`` is therefore never empty, including for the
unclassified fallback.

**The default for an unrecognised high-severity change is NEEDS_REVIEW, not immaterial.**
Silently passing something no rule understands is how an approval quietly stops meaning
anything. ``RULE_UNCLASSIFIED`` exists to make that impossible.

**Rules are pure and take an explicit context.** Everything the engine cannot derive
from the diff itself — which data classes are already approved, which components carry a
critical CVE, what the reviewer's framework forbids — arrives in ``MaterialityContext``.
That is what keeps this file unit-testable without a database, and what lets the same
rule set be evaluated at CI time against a proposed change that has never been deployed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from app.domains.releases.schemas import (
    AccreditationImpact,
    ChangeCategory,
    ChangeOperation,
    Materiality,
    ReleaseDiff,
    SemanticChange,
    Severity,
)

# ----------------------------------------------------------------------
# Context
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class MaterialityContext:
    """Facts the rules need but cannot read off a descriptor diff.

    Defaults are deliberately pessimistic. With an empty ``approved_data_classes`` the
    "read-only tool within an already-approved data class" exemption cannot fire, so an
    engine called without context errs towards review rather than towards approval.
    """

    #: The reviewer's framework. Some frameworks forbid an unreviewed model point-version
    #: bump that the default rules would let through.
    framework_slug: str | None = None

    #: Data classes and regions the current baseline was approved for.
    approved_data_classes: frozenset[str] = frozenset()
    approved_regions: frozenset[str] = frozenset()

    #: Components with an open critical finding, supplied by the assurance domain.
    #: Keyed ``name`` or ``name@version``.
    critical_cve_components: frozenset[str] = frozenset()

    #: Normalised 0..1 semantic distance above which a prompt change is material.
    #: Below it the change is cosmetic. Absent a score the engine will not guess —
    #: see RULE_PROMPT_DRIFT_UNKNOWN. Open question Q-004.
    prompt_drift_threshold: float = 0.15

    #: Per-framework or per-reviewer overrides, keyed by rule id. This is how a
    #: customer's adjudications tune the rule set over time, which is what makes the
    #: moat deepen with use rather than stay fixed at what we shipped.
    overrides: Mapping[str, Materiality] = field(default_factory=dict)

    #: Frameworks that treat any model change as material regardless of step size.
    strict_model_frameworks: frozenset[str] = frozenset({"eu-ai-act"})


# ----------------------------------------------------------------------
# Path helpers
#
# The differ emits stable, structured paths. These parse them rather than matching
# substrings, because `tools[name=payment.post].effect` must not be confused with a
# tool literally named "effect".
# ----------------------------------------------------------------------

_INDEXED = re.compile(r"^(?P<base>[a-z_.]+)\[(?P<key>[a-z_]+)=(?P<value>.*)\]$")
_SET_ITEM = re.compile(r"^(?P<base>[a-z_.]+)\[(?P<item>[^=\]]+)\]$")


def _attribute(path: str) -> str | None:
    """Trailing attribute of an indexed path, or ``None`` for the container itself.

    ``models[role=primary].provider`` -> ``provider``
    ``models[role=primary]``          -> ``None``
    """
    closing = path.rfind("]")
    if closing == -1:
        return path.rsplit(".", 1)[-1] if "." in path else None
    tail = path[closing + 1 :]
    return tail.lstrip(".") or None


def _container(path: str) -> str:
    """Base collection of a path, ignoring index and attribute."""
    closing = path.rfind("]")
    candidate = path if closing == -1 else path[: path.find("[")]
    return candidate


def _set_member(path: str, base: str) -> str | None:
    """Member of a string-set change, e.g. ``data.classes[pii]`` -> ``pii``."""
    match = _SET_ITEM.match(path)
    if match is None or match.group("base") != base:
        return None
    return match.group("item")


def _is_model_attr(change: SemanticChange, attribute: str) -> bool:
    return (
        change.category is ChangeCategory.MODEL
        and change.operation is ChangeOperation.MODIFIED
        and _container(change.path) == "models"
        and _attribute(change.path) == attribute
    )


def _index_value(path: str) -> str | None:
    match = _INDEXED.match(path.split("]")[0] + "]" if "[" in path else path)
    return match.group("value") if match else None


# ----------------------------------------------------------------------
# Value helpers
# ----------------------------------------------------------------------

_BUILD_SUFFIX = re.compile(r"[-@](?:\d{8}|\d{4}-\d{2}-\d{2}|v\d+|latest|preview)$")

#: Ordered least to most autonomous. The three middle-and-upper rungs are the AAP 0.1
#: ``runtime.autonomy`` enum; ``suggest_only`` sits below them for descriptors that
#: declare an advisory-only agent.
_AUTONOMY_LADDER = ("suggest_only", "supervised", "semi_autonomous", "autonomous")

#: Ordered least to most permissive.
#:
#: Consent and safeguards are separate rungs, not spellings of one rung (D-020). They
#: are different bases under GDPR Chapter V and they leave the data in different states:
#:
#:   * Article 46 safeguards — standard contractual clauses, binding corporate rules —
#:     are enforceable obligations that travel with the data and persist after transfer.
#:   * Article 49 explicit consent is a derogation. It authorises the transfer without
#:     protecting the data afterwards, and it can be withdrawn.
#:
#: So moving from safeguards to consent keeps the transfer legal while dropping the
#: ongoing protection, and that is a loosening a reviewer needs to see. Collapsing the
#: two, as this ladder did until Q-007 was answered, made that change invisible.
#:
#: The relative order of the two middle rungs is a legal judgement, not a mechanical
#: one, and is the part of this ladder most worth a lawyer's eye — tracked under Q-001.
_CROSS_BORDER_LADDER = (
    "prohibited",
    "permitted_with_safeguards",
    "permitted_with_consent",
    "permitted",
)

#: Ordered weakest to strongest.
_AUTH_LADDER = ("none", "api_key", "basic", "oauth2", "oidc", "mtls", "workload_identity")

#: Spellings seen in real descriptors, mapped to the rung they occupy.
#:
#: This map is the difference between a rule that fires and a rule that silently does
#: not. ``oauth2_client_credentials`` is what descriptors actually carry, and before it
#: was mapped, downgrading to an API key placed neither end on the ladder and the
#: material verdict was never reached.
_LADDER_SYNONYMS: Mapping[str, str] = {
    # Autonomy
    "human_in_the_loop": "supervised",
    "human_in_loop": "supervised",
    "advisory": "suggest_only",
    "recommend_only": "suggest_only",
    "human_on_the_loop": "semi_autonomous",
    "human_on_loop": "semi_autonomous",
    "fully_autonomous": "autonomous",
    # Cross-border transfer. Standard contractual clauses and binding corporate rules
    # are both Article 46 instruments, so they land on the safeguards rung. Consent
    # keeps its own rung and is deliberately absent from this map.
    "with_safeguards": "permitted_with_safeguards",
    "permitted_with_scc": "permitted_with_safeguards",
    "permitted_with_sccs": "permitted_with_safeguards",
    "permitted_with_bcr": "permitted_with_safeguards",
    "with_consent": "permitted_with_consent",
    "explicit_consent": "permitted_with_consent",
    # Authentication
    "oauth2_client_credentials": "oauth2",
    "client_credentials": "oauth2",
    "oauth": "oauth2",
    "bearer_token": "api_key",
    "bearer": "api_key",
    "static_token": "api_key",
    "basic_auth": "basic",
    "openid_connect": "oidc",
    "mutual_tls": "mtls",
    "spiffe": "workload_identity",
    "irsa": "workload_identity",
    "managed_identity": "workload_identity",
}

#: Paths whose verdict is decided by movement along a ladder. If a change on one of
#: these cannot be placed, RULE_LADDER_UNKNOWN escalates it rather than letting it pass.
_LADDER_PATHS: Mapping[str, Sequence[str]] = {
    "runtime.autonomy": _AUTONOMY_LADDER,
    "data.residency.cross_border": _CROSS_BORDER_LADDER,
    "security.authentication": _AUTH_LADDER,
}

_WRITE_EFFECTS = frozenset({"write", "delete", "execute", "payment", "irreversible"})


def _as_text(value: object) -> str:
    return "" if value is None else str(value).strip().lower()


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _ladder_rung(value: object, ladder: Sequence[str]) -> int | None:
    """Position of ``value`` on ``ladder``, resolving known synonyms first."""
    text = _as_text(value)
    canonical = _LADDER_SYNONYMS.get(text, text)
    try:
        return ladder.index(canonical)
    except ValueError:
        return None


def _ladder_move(before: object, after: object, ladder: Sequence[str]) -> int | None:
    """Signed movement along an ordered vocabulary, or ``None`` if either end is
    unrecognised. Positive means "more permissive"."""
    lo = _ladder_rung(before, ladder)
    hi = _ladder_rung(after, ladder)
    if lo is None or hi is None:
        return None
    return hi - lo


def _model_id_step(before: object, after: object) -> str:
    """Classify a model identifier change.

    A heuristic, and labelled as one. Model identifiers are not semver:
    ``claude-sonnet-4-5-20250929`` and ``gpt-4o-2024-08-06`` both carry a build suffix
    that moves without the model's behaviour contract changing. The classification is
    deliberately conservative — anything it cannot parse becomes ``unknown``, which
    routes to a human rather than to an assumption.
    """
    raw_before, raw_after = _as_text(before), _as_text(after)
    if not raw_before or not raw_after:
        return "unknown"

    stripped_before = _BUILD_SUFFIX.sub("", raw_before)
    stripped_after = _BUILD_SUFFIX.sub("", raw_after)

    if stripped_before == stripped_after:
        # Only the dated build moved: same declared model, newer snapshot.
        return "point"

    parts_before = stripped_before.replace(".", "-").split("-")
    parts_after = stripped_after.replace(".", "-").split("-")
    if len(parts_before) != len(parts_after):
        return "unknown"

    differing = [
        i for i, (b, a) in enumerate(zip(parts_before, parts_after, strict=True)) if b != a
    ]
    if len(differing) != 1:
        return "unknown"

    position = differing[0]
    if not (parts_before[position].isdigit() and parts_after[position].isdigit()):
        # A word changed — "sonnet" to "opus" is not a version step.
        return "unknown"

    numeric_positions = [i for i, p in enumerate(parts_before) if p.isdigit()]
    return "minor" if position == max(numeric_positions) else "major"


def _drift_score(change: SemanticChange) -> float | None:
    """Semantic distance for a prompt change, when the descriptor supplied one.

    We hold prompt *digests*, never prompt text (AGENTS.md rule 5), so the engine
    cannot compute this itself. A publisher that runs its own similarity check can
    declare the result; one that does not gets a review rather than a guess.
    """
    for value in (change.after_value, change.before_value):
        if isinstance(value, dict):
            score = _as_number(value.get("drift_score"))
            if score is not None:
                return score
    return None


# ----------------------------------------------------------------------
# Rule definition
# ----------------------------------------------------------------------

Predicate = Callable[[SemanticChange, MaterialityContext], bool]


@dataclass(frozen=True)
class Rule:
    """One named, auditable decision.

    ``rationale`` is rendered in the console next to the verdict, so it is written for
    the agent's owner — the person who will disagree with it — rather than for us.
    """

    id: str
    title: str
    verdict: Materiality
    rationale: str
    matches: Predicate


def _r(
    rule_id: str,
    title: str,
    verdict: Materiality,
    rationale: str,
    matches: Predicate,
) -> Rule:
    return Rule(rule_id, title, verdict, rationale, matches)


# ----------------------------------------------------------------------
# MATERIAL — the approval is invalidated
# ----------------------------------------------------------------------

MATERIAL_RULES: tuple[Rule, ...] = (
    _r(
        "MAT-001-model-provider",
        "Model provider changed",
        Materiality.MATERIAL,
        "A different provider means different data-processing terms, a different "
        "retention policy and a different processing location. The existing approval "
        "describes where data went under the old provider and no longer applies.",
        lambda c, _: _is_model_attr(c, "provider"),
    ),
    _r(
        "MAT-002-model-family",
        "Model family changed",
        Materiality.MATERIAL,
        "Evaluation results do not transfer between model families. Whatever testing "
        "supported the original approval was performed against a different model.",
        lambda c, _: _is_model_attr(c, "family"),
    ),
    _r(
        "MAT-003-model-hosting",
        "Model hosting mode changed",
        Materiality.MATERIAL,
        "Moving between a vendor API, a managed cloud endpoint and self-hosting changes "
        "the residency and retention posture entirely.",
        lambda c, _: _is_model_attr(c, "hosting"),
    ),
    _r(
        "MAT-004-model-region",
        "Model endpoint region changed",
        Materiality.MATERIAL,
        "The agent now processes data in a location the approval did not cover.",
        lambda c, _: _is_model_attr(c, "endpoint_region"),
    ),
    _r(
        "MAT-005-model-added",
        "A model was added",
        Materiality.MATERIAL,
        "A new model brings its own provider terms, retention policy and processing "
        "region, none of which have been reviewed.",
        lambda c, _: (
            c.category is ChangeCategory.MODEL
            and c.operation is ChangeOperation.ADDED
            and _attribute(c.path) is None
        ),
    ),
    _r(
        "MAT-006-data-class-added",
        "A new data class is touched",
        Materiality.MATERIAL,
        "The agent now handles a category of data it was not approved for. This is the "
        "change a customer's privacy team asks about first.",
        lambda c, ctx: (
            c.operation is ChangeOperation.ADDED
            and (
                (member := _set_member(c.path, "data.classes")) is not None
                and member not in ctx.approved_data_classes
            )
        ),
    ),
    _r(
        "MAT-007-special-category-added",
        "Special-category data is now processed",
        Materiality.MATERIAL,
        "Special-category data carries an elevated regulatory duty and almost always "
        "requires a fresh impact assessment.",
        lambda c, _: (
            c.operation is ChangeOperation.ADDED
            and _set_member(c.path, "data.special_categories") is not None
        ),
    ),
    _r(
        "MAT-008-region-added",
        "A new processing region appears",
        Materiality.MATERIAL,
        "An agent approved for one set of regions is now permitted to process "
        "elsewhere, which is the concern behind every data-residency question.",
        lambda c, ctx: (
            c.operation is ChangeOperation.ADDED
            and (
                (member := _set_member(c.path, "data.residency.permitted_regions")) is not None
                and member not in ctx.approved_regions
            )
        ),
    ),
    _r(
        "MAT-009-cross-border-loosened",
        "Cross-border transfer stance loosened",
        Materiality.MATERIAL,
        "The constraint that kept data inside its jurisdiction has been relaxed.",
        lambda c, _: (
            c.path == "data.residency.cross_border"
            and (move := _ladder_move(c.before_value, c.after_value, _CROSS_BORDER_LADDER))
            is not None
            and move > 0
        ),
    ),
    _r(
        "MAT-010-write-tool-added",
        "A tool with write effect was added",
        Materiality.MATERIAL,
        "The agent has gained the ability to change a system of record. New mutation "
        "capability is material regardless of how well tested it is.",
        lambda c, _: (
            c.category is ChangeCategory.TOOL
            and c.operation is ChangeOperation.ADDED
            and _attribute(c.path) is None
            and isinstance(c.after_value, dict)
            and _as_text(c.after_value.get("effect")) in _WRITE_EFFECTS
        ),
    ),
    _r(
        "MAT-011-tool-effect-escalated",
        "An existing tool gained write access",
        Materiality.MATERIAL,
        "A tool reviewed as read-only can now mutate data. The approval was granted on "
        "the narrower behaviour.",
        lambda c, _: (
            _attribute(c.path) == "effect"
            and _as_text(c.before_value) not in _WRITE_EFFECTS
            and _as_text(c.after_value) in _WRITE_EFFECTS
        ),
    ),
    _r(
        "MAT-012-irreversible-capability",
        "An irreversible capability was introduced",
        Materiality.MATERIAL,
        "An action that cannot be compensated has a different risk profile from one "
        "that can be undone, whatever its success rate.",
        lambda c, _: (
            (
                _attribute(c.path) == "reversible"
                and c.before_value is True
                and c.after_value is False
            )
            or (
                c.operation is ChangeOperation.ADDED
                and isinstance(c.after_value, dict)
                and c.after_value.get("reversible") is False
            )
        ),
    ),
    _r(
        "MAT-013-oversight-removed",
        "Human-approval requirement removed",
        Materiality.MATERIAL,
        "An oversight control has been weakened. This is the change most likely to be "
        "made for convenience and least likely to be flagged by its author.",
        lambda c, _: (
            _attribute(c.path) == "human_approval"
            and _as_text(c.before_value) not in ("", "none", "not_required")
            and _as_text(c.after_value) in ("none", "not_required", "")
        ),
    ),
    _r(
        "MAT-014-guardrail-removed",
        "An injection defence was removed",
        Materiality.MATERIAL,
        "A control that was part of the approved security posture is no longer present.",
        lambda c, _: (
            c.operation is ChangeOperation.REMOVED
            and _set_member(c.path, "security.prompt_injection_defences") is not None
        ),
    ),
    _r(
        "MAT-015-critical-cve",
        "A component with a critical vulnerability entered the bill of materials",
        Materiality.MATERIAL,
        "A dependency with a known critical vulnerability is in the agent's supply "
        "chain. No approval survives that until it is remediated or accepted.",
        lambda c, ctx: (
            c.operation in (ChangeOperation.ADDED, ChangeOperation.MODIFIED)
            and bool(ctx.critical_cve_components)
            and _component_matches_cve(c, ctx)
        ),
    ),
    _r(
        "MAT-016-autonomy-raised",
        "Autonomy level raised",
        Materiality.MATERIAL,
        "The agent now acts with less human involvement than the approval assumed.",
        lambda c, _: (
            c.path == "runtime.autonomy"
            and (move := _ladder_move(c.before_value, c.after_value, _AUTONOMY_LADDER)) is not None
            and move > 0
        ),
    ),
    _r(
        "MAT-017-retention-extended",
        "Data retention period extended",
        Materiality.MATERIAL,
        "Data is kept longer than the approved period, which most data-processing "
        "agreements specify explicitly.",
        lambda c, _: (
            c.path == "data.retention_days"
            and (before := _as_number(c.before_value)) is not None
            and (after := _as_number(c.after_value)) is not None
            and after > before
        ),
    ),
    _r(
        "MAT-018-auth-weakened",
        "Authentication weakened",
        Materiality.MATERIAL,
        "The agent authenticates to its dependencies more weakly than when approved.",
        lambda c, _: (
            c.path == "security.authentication"
            and (move := _ladder_move(c.before_value, c.after_value, _AUTH_LADDER)) is not None
            and move < 0
        ),
    ),
    _r(
        "MAT-019-value-limit-raised",
        "Transaction value limit raised",
        Materiality.MATERIAL,
        "The financial ceiling the approval was granted against has moved.",
        lambda c, _: (
            c.path.endswith(".value_limit.max")
            and (before := _as_number(c.before_value)) is not None
            and (after := _as_number(c.after_value)) is not None
            and after > before
        ),
    ),
    _r(
        "MAT-020-prompt-drift",
        "System prompt changed beyond the drift threshold",
        Materiality.MATERIAL,
        "The declared semantic distance between the old and new instructions exceeds "
        "the threshold, so this is a behavioural change rather than an edit.",
        lambda c, ctx: (
            c.category is ChangeCategory.PROMPT
            and (score := _drift_score(c)) is not None
            and score > ctx.prompt_drift_threshold
        ),
    ),
    _r(
        "MAT-021-egress-added",
        "A new egress destination appears",
        Materiality.MATERIAL,
        "The agent can now reach a network destination outside the approved boundary.",
        lambda c, _: (
            c.operation is ChangeOperation.ADDED
            and _set_member(c.path, "security.network_egress") is not None
        ),
    ),
    _r(
        "MAT-022-model-policy-auto",
        "Model selection set to automatic routing",
        Materiality.MATERIAL,
        "Automatic routing can send production data to models outside the approved "
        "catalogue without a further review gate.",
        lambda c, _: (
            c.category is ChangeCategory.MODEL_POLICY
            and c.path.endswith("selection_mode")
            and _as_text(c.after_value) == "auto"
        ),
    ),
    _r(
        "MAT-023-obligation-forbid-weakened",
        "A forbidding obligation was weakened",
        Materiality.MATERIAL,
        "A rule that forbade a category of behaviour was relaxed or inverted.",
        lambda c, _: (
            c.category is ChangeCategory.RULE_OBLIGATION
            and c.path.endswith(".polarity")
            and _as_text(c.before_value) == "forbid"
            and _as_text(c.after_value) != "forbid"
        ),
    ),
    _r(
        "MAT-024-sub-agent-external",
        "An external sub-agent was added",
        Materiality.MATERIAL,
        "Delegation now reaches a partner or external agent outside the internal "
        "accreditation boundary.",
        lambda c, _: (
            c.category is ChangeCategory.SUB_AGENT
            and c.operation is ChangeOperation.ADDED
            and isinstance(c.after_value, dict)
            and _as_text(c.after_value.get("trust")) not in ("internal", "internal_accredited", "")
        ),
    ),
)


def _component_matches_cve(change: SemanticChange, ctx: MaterialityContext) -> bool:
    """Whether the component this change concerns carries an open critical finding.

    Matches on bare name and on ``name@version``, because a CVE is usually pinned to a
    version while a descriptor may name either.
    """
    index = _index_value(change.path)
    candidates: set[str] = set()
    if index:
        candidates.add(index.lower())
    for value in (change.after_value, change.before_value):
        if isinstance(value, dict):
            name = _as_text(value.get("name"))
            version = _as_text(value.get("version"))
            if name:
                candidates.add(name)
                if version:
                    candidates.add(f"{name}@{version}")
    lowered = {c.lower() for c in ctx.critical_cve_components}
    return bool(candidates & lowered)


# ----------------------------------------------------------------------
# IMMATERIAL — logged, the approval stands
# ----------------------------------------------------------------------

IMMATERIAL_RULES: tuple[Rule, ...] = (
    _r(
        "IMM-001-model-point-version",
        "Model point-version bump within the same family",
        Materiality.IMMATERIAL,
        "The declared model is unchanged; only the dated build moved. Recorded as "
        "evidence and the baseline advances.",
        lambda c, ctx: (
            _is_model_attr(c, "id")
            and _model_id_step(c.before_value, c.after_value) == "point"
            and (ctx.framework_slug or "") not in ctx.strict_model_frameworks
        ),
    ),
    _r(
        "IMM-002-dependency-patch",
        "Library patch version with no vulnerability delta",
        Materiality.IMMATERIAL,
        "A patch-level bump with no known critical vulnerability entering the bill of materials.",
        lambda c, ctx: (
            c.category is ChangeCategory.DEPENDENCY
            and c.operation is ChangeOperation.MODIFIED
            and not _component_matches_cve(c, ctx)
            and _is_patch_bump(c.before_value, c.after_value)
        ),
    ),
    _r(
        "IMM-003-prompt-cosmetic",
        "Prompt change below the drift threshold",
        Materiality.IMMATERIAL,
        "Whitespace, formatting or a typo correction. The declared semantic distance is "
        "within the threshold.",
        lambda c, ctx: (
            c.category is ChangeCategory.PROMPT
            and (score := _drift_score(c)) is not None
            and score <= ctx.prompt_drift_threshold
        ),
    ),
    _r(
        "IMM-004-metadata-only",
        "Descriptive metadata only",
        Materiality.IMMATERIAL,
        "Naming, description or tagging. Nothing the agent does has changed.",
        lambda c, _: c.category is ChangeCategory.METADATA,
    ),
    _r(
        "IMM-005-readonly-tool-in-scope",
        "Read-only tool added within an already-approved data class",
        Materiality.IMMATERIAL,
        "The tool cannot mutate anything and reaches only data the approval already covers.",
        lambda c, ctx: (
            c.category is ChangeCategory.TOOL
            and c.operation is ChangeOperation.ADDED
            and isinstance(c.after_value, dict)
            and _as_text(c.after_value.get("effect")) == "read"
            and bool(ctx.approved_data_classes)
            and _declared_classes(c.after_value) <= ctx.approved_data_classes
        ),
    ),
    _r(
        "IMM-006-resilience-tightened",
        "Resilience configuration tightened",
        Materiality.IMMATERIAL,
        "A shorter timeout, more retries or a lower failure threshold make the agent "
        "more robust rather than less.",
        lambda c, _: _resilience_direction(c) == "tightened",
    ),
    _r(
        "IMM-007-determinism-improved",
        "Output made more deterministic",
        Materiality.IMMATERIAL,
        "A fixed seed or a lower sampling temperature makes behaviour more reproducible, "
        "which strengthens rather than weakens the basis for the approval.",
        lambda c, _: (
            (c.path == "inference.seed" and c.before_value is None and c.after_value is not None)
            or (
                c.path in ("inference.temperature", "inference.top_p")
                and (before := _as_number(c.before_value)) is not None
                and (after := _as_number(c.after_value)) is not None
                and after < before
            )
        ),
    ),
    _r(
        "IMM-008-cross-border-tightened",
        "Cross-border transfer stance tightened",
        Materiality.IMMATERIAL,
        "A stricter transfer constraint than the one approved.",
        lambda c, _: (
            c.path == "data.residency.cross_border"
            and (move := _ladder_move(c.before_value, c.after_value, _CROSS_BORDER_LADDER))
            is not None
            and move < 0
        ),
    ),
    _r(
        "IMM-009-region-removed",
        "A permitted region was withdrawn",
        Materiality.IMMATERIAL,
        "Narrowing where data may be processed cannot invalidate an approval granted "
        "over a wider set.",
        lambda c, _: (
            c.operation is ChangeOperation.REMOVED
            and _set_member(c.path, "data.residency.permitted_regions") is not None
        ),
    ),
    # The mirror of MAT-017. Without it, shortening retention reaches the unclassified
    # fallback and asks a human to approve a change that strictly reduces exposure —
    # which trains reviewers to dismiss the queue.
    _r(
        "IMM-010-retention-shortened",
        "Data retention period shortened",
        Materiality.IMMATERIAL,
        "Data is kept for less time than the approval permitted, which reduces "
        "exposure rather than increasing it.",
        lambda c, _: (
            c.path == "data.retention_days"
            and (before := _as_number(c.before_value)) is not None
            and (after := _as_number(c.after_value)) is not None
            and after < before
        ),
    ),
    _r(
        "IMM-011-data-class-removed",
        "A data class is no longer touched",
        Materiality.IMMATERIAL,
        "The agent handles less data than the approval covered.",
        lambda c, _: (
            c.operation is ChangeOperation.REMOVED
            and (
                _set_member(c.path, "data.classes") is not None
                or _set_member(c.path, "data.special_categories") is not None
            )
        ),
    ),
    _r(
        "IMM-012-tool-removed",
        "A tool or capability was removed",
        Materiality.IMMATERIAL,
        "Removing a capability narrows what the agent can attempt. The approval was "
        "granted over the wider set.",
        lambda c, _: (
            c.category in (ChangeCategory.TOOL, ChangeCategory.CAPABILITY)
            and c.operation is ChangeOperation.REMOVED
            and _attribute(c.path) is None
        ),
    ),
    _r(
        "IMM-013-oversight-strengthened",
        "Human-approval requirement added or strengthened",
        Materiality.IMMATERIAL,
        "An oversight control is stronger than the one approved.",
        lambda c, _: (
            _attribute(c.path) == "human_approval"
            and _as_text(c.before_value) in ("", "none", "not_required")
            and _as_text(c.after_value) not in ("", "none", "not_required")
        ),
    ),
    _r(
        "IMM-014-value-limit-lowered",
        "Transaction value limit lowered",
        Materiality.IMMATERIAL,
        "A tighter financial ceiling than the one approved.",
        lambda c, _: (
            c.path.endswith(".value_limit.max")
            and (before := _as_number(c.before_value)) is not None
            and (after := _as_number(c.after_value)) is not None
            and after < before
        ),
    ),
    _r(
        "IMM-015-autonomy-lowered",
        "Autonomy level lowered",
        Materiality.IMMATERIAL,
        "The agent acts with more human involvement than the approval assumed.",
        lambda c, _: (
            c.path == "runtime.autonomy"
            and (move := _ladder_move(c.before_value, c.after_value, _AUTONOMY_LADDER)) is not None
            and move < 0
        ),
    ),
    _r(
        "IMM-016-auth-strengthened",
        "Authentication strengthened",
        Materiality.IMMATERIAL,
        "The agent authenticates to its dependencies more strongly than when approved.",
        lambda c, _: (
            c.path == "security.authentication"
            and (move := _ladder_move(c.before_value, c.after_value, _AUTH_LADDER)) is not None
            and move > 0
        ),
    ),
    _r(
        "IMM-019-vocabulary-equivalent",
        "A governed setting was reworded without changing what it permits",
        Materiality.IMMATERIAL,
        "The new value sits at the same level of permissiveness as the approved one, so "
        "nothing about what the agent may do has changed.",
        lambda c, _: (
            c.path in _LADDER_PATHS
            and c.before_value != c.after_value
            and _ladder_move(c.before_value, c.after_value, _LADDER_PATHS[c.path]) == 0
        ),
    ),
    _r(
        "IMM-017-guardrail-added",
        "An injection defence was added",
        Materiality.IMMATERIAL,
        "A control has been added to the approved security posture.",
        lambda c, _: (
            c.operation is ChangeOperation.ADDED
            and _set_member(c.path, "security.prompt_injection_defences") is not None
        ),
    ),
    _r(
        "IMM-018-egress-removed",
        "An egress destination was removed",
        Materiality.IMMATERIAL,
        "The agent can reach fewer network destinations than the approval permitted.",
        lambda c, _: (
            c.operation is ChangeOperation.REMOVED
            and _set_member(c.path, "security.network_egress") is not None
        ),
    ),
    _r(
        "IMM-020-composition-renamed",
        "A composition element was renamed without changing its contents",
        Materiality.IMMATERIAL,
        "Only the identifier changed; the underlying skill, config or obligation text "
        "is unchanged.",
        lambda c, _: c.operation is ChangeOperation.RENAMED and c.path.startswith("composition."),
    ),
)


def _declared_classes(value: object) -> frozenset[str]:
    if not isinstance(value, dict):
        return frozenset()
    raw = value.get("data_classes") or value.get("classes") or []
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(_as_text(v) for v in raw if _as_text(v))


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _is_patch_bump(before: object, after: object) -> bool:
    """True only for a same-major, same-minor version move.

    Returns False when either end is unparseable, so an unrecognised version scheme
    falls through to review rather than being waved past as a patch.
    """
    for candidate in (before, after):
        if isinstance(candidate, dict):
            return _is_patch_bump(candidate.get("version"), after)

    match_before = _SEMVER.match(_as_text(before))
    match_after = _SEMVER.match(_as_text(after))
    if not (match_before and match_after):
        return False
    return match_before.group(1, 2) == match_after.group(1, 2)


_TIGHTEN_LOWER = ("resilience.request_timeout_ms", "inference.max_tokens")
_TIGHTEN_HIGHER = ("resilience.max_retries",)


def _resilience_direction(change: SemanticChange) -> str | None:
    """``tightened``, ``loosened``, or ``None`` when the path is not a resilience knob."""
    before, after = _as_number(change.before_value), _as_number(change.after_value)
    if before is None or after is None or before == after:
        return None
    if change.path in _TIGHTEN_LOWER:
        return "tightened" if after < before else "loosened"
    if change.path in _TIGHTEN_HIGHER:
        return "tightened" if after > before else "loosened"
    if change.path == "resilience.circuit_breaker.failure_threshold":
        return "tightened" if after < before else "loosened"
    if change.path == "resilience.rate_limit.requests_per_minute":
        return "tightened" if after < before else "loosened"
    return None


# ----------------------------------------------------------------------
# NEEDS REVIEW — routed to a human, and the decision tunes the rule set
# ----------------------------------------------------------------------

REVIEW_RULES: tuple[Rule, ...] = (
    _r(
        "REV-001-model-minor-version",
        "Model minor-version change where the framework is silent",
        Materiality.NEEDS_REVIEW,
        "A minor version can change behaviour without changing the family. The "
        "reviewer's framework does not say whether that requires revalidation.",
        lambda c, _: (
            _is_model_attr(c, "id") and _model_id_step(c.before_value, c.after_value) == "minor"
        ),
    ),
    _r(
        "REV-002-model-version-unclear",
        "Model identifier changed in a way that cannot be classified",
        Materiality.NEEDS_REVIEW,
        "The identifier does not follow a scheme this engine can compare, so the size "
        "of the change is unknown.",
        lambda c, _: (
            _is_model_attr(c, "id") and _model_id_step(c.before_value, c.after_value) == "unknown"
        ),
    ),
    _r(
        "REV-003-model-strict-framework",
        "Model changed under a framework that reviews every model change",
        Materiality.NEEDS_REVIEW,
        "The reviewer's framework does not accept an unreviewed model change, even a "
        "point-version bump.",
        lambda c, ctx: (
            _is_model_attr(c, "id") and (ctx.framework_slug or "") in ctx.strict_model_frameworks
        ),
    ),
    _r(
        "REV-004-prompt-drift-unknown",
        "Prompt changed with no declared semantic distance",
        Materiality.NEEDS_REVIEW,
        "The instructions changed but no drift score was declared. Prompt text is not "
        "stored, so the size of the change cannot be computed here — a human must "
        "decide whether it is cosmetic.",
        lambda c, _: c.category is ChangeCategory.PROMPT and _drift_score(c) is None,
    ),
    _r(
        "REV-005-tool-effect-unknown",
        "New tool whose effect cannot be determined from its metadata",
        Materiality.NEEDS_REVIEW,
        "The tool declares no effect, so whether it can mutate data is unknown. Tool "
        "metadata is self-declared and is not trusted by default.",
        lambda c, _: (
            c.category is ChangeCategory.TOOL
            and c.operation is ChangeOperation.ADDED
            and _attribute(c.path) is None
            and (
                not isinstance(c.after_value, dict)
                or _as_text(c.after_value.get("effect")) not in _WRITE_EFFECTS | {"read"}
            )
        ),
    ),
    _r(
        "REV-018-tool-scope-unknown",
        "A read-only tool was added but the approved data scope is not known",
        Materiality.NEEDS_REVIEW,
        "A read-only tool still reaches data. Whether it stays inside what this client "
        "approved cannot be determined because no approved data classes are recorded, so "
        "it needs a decision rather than an assumption.",
        lambda c, ctx: (
            c.category is ChangeCategory.TOOL
            and c.operation is ChangeOperation.ADDED
            and _attribute(c.path) is None
            and isinstance(c.after_value, dict)
            and _as_text(c.after_value.get("effect")) == "read"
            and not ctx.approved_data_classes
        ),
    ),
    _r(
        "REV-006-mcp-server-added",
        "An MCP server was added",
        Materiality.NEEDS_REVIEW,
        "An MCP server can expose tools that change after registration, and its "
        "annotations are self-declared. The tool set it offers needs review.",
        lambda c, _: (
            c.category is ChangeCategory.MCP_SERVER and c.operation is ChangeOperation.ADDED
        ),
    ),
    _r(
        "REV-007-mcp-contents-changed",
        "An MCP server's contents changed",
        Materiality.NEEDS_REVIEW,
        "The server's advertised tool set no longer matches what was reviewed. Its "
        "capabilities may have widened without any change to this agent.",
        lambda c, _: c.category is ChangeCategory.MCP_SERVER and _attribute(c.path) == "digest",
    ),
    _r(
        "REV-008-delegation-added",
        "Delegation to another agent was added",
        Materiality.NEEDS_REVIEW,
        "This agent can now reach whatever the delegate can reach. Its blast radius "
        "has grown by the whole of the delegate's.",
        lambda c, _: (
            c.category is ChangeCategory.DELEGATION and c.operation is ChangeOperation.ADDED
        ),
    ),
    _r(
        "REV-009-data-source-added",
        "A data source was added",
        Materiality.NEEDS_REVIEW,
        "A new source may introduce data classes or a processing region the approval "
        "does not cover.",
        lambda c, _: (
            c.category is ChangeCategory.DATA_SOURCE
            and c.operation is ChangeOperation.ADDED
            and _attribute(c.path) is None
        ),
    ),
    _r(
        "REV-010-data-source-region",
        "A data source's region changed",
        Materiality.NEEDS_REVIEW,
        "Data is being read from a different location than the approval recorded.",
        lambda c, _: c.category is ChangeCategory.DATA_SOURCE and _attribute(c.path) == "region",
    ),
    _r(
        "REV-011-resilience-loosened",
        "Resilience configuration loosened",
        Materiality.NEEDS_REVIEW,
        "A longer timeout, fewer retries or a higher failure threshold may put an "
        "availability commitment at risk.",
        lambda c, _: _resilience_direction(c) == "loosened",
    ),
    _r(
        "REV-012-fallback-model",
        "Fallback model changed",
        Materiality.NEEDS_REVIEW,
        "A fallback runs under the same approval as the primary, and often in a "
        "different region — it is reviewed less often and matters just as much.",
        lambda c, _: c.path == "resilience.fallback_model",
    ),
    _r(
        "REV-013-framework-change",
        "Runtime framework changed",
        Materiality.NEEDS_REVIEW,
        "A different orchestration framework changes how the agent handles tool errors, "
        "retries and partial failure.",
        lambda c, _: c.path in ("runtime.framework", "runtime.framework_version"),
    ),
    _r(
        "REV-014-temperature-raised",
        "Sampling temperature raised",
        Materiality.NEEDS_REVIEW,
        "Less deterministic output makes prior evaluation results a weaker basis for the approval.",
        lambda c, _: (
            c.path in ("inference.temperature", "inference.top_p")
            and (before := _as_number(c.before_value)) is not None
            and (after := _as_number(c.after_value)) is not None
            and after > before
        ),
    ),
    _r(
        "REV-015-capability-added",
        "A capability was added",
        Materiality.NEEDS_REVIEW,
        "A new declared capability widens what the agent is permitted to attempt.",
        lambda c, _: (
            c.category is ChangeCategory.CAPABILITY
            and c.operation is ChangeOperation.ADDED
            and _attribute(c.path) is None
        ),
    ),
    _r(
        "REV-016-secrets-source",
        "Secrets source changed",
        Materiality.NEEDS_REVIEW,
        "Where credentials come from is part of the approved security posture.",
        lambda c, _: c.path == "security.secrets_source",
    ),
    _r(
        "REV-019-skill-added",
        "A skill was added to the composition",
        Materiality.NEEDS_REVIEW,
        "Skills bundle instructions and tools; a new one widens what the agent may attempt.",
        lambda c, _: c.category is ChangeCategory.SKILL and c.operation is ChangeOperation.ADDED,
    ),
    _r(
        "REV-020-config-changed",
        "A configuration entry changed",
        Materiality.NEEDS_REVIEW,
        "Configuration shapes runtime behaviour even when application code is unchanged.",
        lambda c, _: (
            c.category is ChangeCategory.CONFIG and c.operation is ChangeOperation.MODIFIED
        ),
    ),
    _r(
        "REV-021-rule-obligation-added",
        "A rule obligation was added",
        Materiality.NEEDS_REVIEW,
        "New obligations change the compliance story even when application code looks the same.",
        lambda c, _: (
            c.category is ChangeCategory.RULE_OBLIGATION and c.operation is ChangeOperation.ADDED
        ),
    ),
    _r(
        "REV-022-model-policy-tuned",
        "Model policy changed without enabling automatic routing",
        Materiality.NEEDS_REVIEW,
        "Allowlists, pins and denylists decide which models may see production data.",
        lambda c, _: (
            c.category is ChangeCategory.MODEL_POLICY
            and c.operation is ChangeOperation.MODIFIED
            and not c.path.endswith("selection_mode")
        ),
    ),
    _r(
        "REV-023-composition-attribute-unclassified",
        "A composition attribute changed with no specific rule",
        Materiality.NEEDS_REVIEW,
        "Unrecognised composition changes default to review rather than cosmetic.",
        lambda c, _: (
            c.path.startswith("composition.")
            and c.operation is ChangeOperation.MODIFIED
            and c.severity in (Severity.HIGH, Severity.CRITICAL)
        ),
    ),
)

#: The fallback. Fires when nothing else does and the change is significant enough that
#: silence would be the wrong answer.
#:
#: This rule is the reason the engine is safe to ship with an incomplete rule set: a
#: change nobody anticipated reaches a human instead of quietly passing. Every time it
#: fires on something real, that is the signal to write a specific rule.
#: Fires when a ladder-governed field moves but neither end can be placed on its ladder.
#:
#: Without this, an unrecognised vocabulary value makes the material and immaterial
#: ladder rules both evaluate false, and the change falls through to severity-based
#: handling — so a descriptor using an unknown word for "fully autonomous" could pass as
#: immaterial. Escalating instead means an unfamiliar vocabulary costs a review, which is
#: the right price.
RULE_LADDER_UNKNOWN = _r(
    "REV-017-vocabulary-unknown",
    "A governed setting changed to an unrecognised value",
    Materiality.NEEDS_REVIEW,
    "This setting is judged by how permissive the new value is, and the value is not one "
    "this version of the rule set knows. It cannot be ruled automatically.",
    lambda c, _: (
        c.path in _LADDER_PATHS
        and c.before_value != c.after_value
        and _ladder_move(c.before_value, c.after_value, _LADDER_PATHS[c.path]) is None
    ),
)

RULE_UNCLASSIFIED = _r(
    "REV-000-unclassified",
    "Significant change with no matching rule",
    Materiality.NEEDS_REVIEW,
    "No rule in the current set describes this change, and its severity is too high to "
    "pass without a decision. Adjudicating it here is what teaches the rule set.",
    lambda c, _: c.severity in (Severity.CRITICAL, Severity.HIGH),
)

#: Fires when nothing matches and the change is minor. Named so that even a trivially
#: immaterial change carries a rule id — a verdict without a rule cannot be audited.
RULE_NO_IMPACT = _r(
    "IMM-000-no-assurance-impact",
    "No assurance impact",
    Materiality.IMMATERIAL,
    "No rule identifies an assurance consequence, and the change is low severity. "
    "Recorded as evidence and the baseline advances.",
    lambda _c, _ctx: True,
)

ALL_RULES: tuple[Rule, ...] = (
    MATERIAL_RULES + IMMATERIAL_RULES + REVIEW_RULES + (RULE_LADDER_UNKNOWN,)
)

RULES_BY_ID: dict[str, Rule] = {r.id: r for r in (*ALL_RULES, RULE_UNCLASSIFIED, RULE_NO_IMPACT)}


# ----------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------

#: Strongest wins. A change that is both immaterial by one rule and material by another
#: is material — the conservative direction is the only defensible one when the output
#: is whether a customer's approval still holds.
_PRECEDENCE: dict[Materiality, int] = {
    Materiality.IMMATERIAL: 0,
    Materiality.NEEDS_REVIEW: 1,
    Materiality.MATERIAL: 2,
}


@dataclass(frozen=True)
class ChangeVerdict:
    verdict: Materiality
    rules_fired: tuple[str, ...]
    rationale: tuple[str, ...]


def evaluate_change(
    change: SemanticChange, context: MaterialityContext | None = None
) -> ChangeVerdict:
    """Rule the verdict on one change.

    Every rule is evaluated, not just the first to match, because a reviewer needs to
    see every reason a change was flagged. A model swap that also moves region should
    say both.
    """
    ctx = context or MaterialityContext()
    fired: list[Rule] = []

    for rule in ALL_RULES:
        try:
            if rule.matches(change, ctx):
                fired.append(rule)
        except Exception:
            # A predicate that raises on an unexpected descriptor shape must not take
            # the whole evaluation with it. Treating it as "did not match" is safe:
            # the unclassified fallback still catches anything significant.
            continue

    if not fired:
        fallback = RULE_UNCLASSIFIED if RULE_UNCLASSIFIED.matches(change, ctx) else RULE_NO_IMPACT
        fired = [fallback]

    # An override lets a customer's earlier adjudication decide this rule's verdict.
    effective = [(ctx.overrides.get(r.id, r.verdict), r) for r in fired]
    winner = max(effective, key=lambda pair: _PRECEDENCE[pair[0]])[0]

    return ChangeVerdict(
        verdict=winner,
        rules_fired=tuple(r.id for _, r in effective),
        rationale=tuple(r.rationale for v, r in effective if v == winner),
    )


def apply_verdicts(
    changes: Sequence[SemanticChange], context: MaterialityContext | None = None
) -> list[SemanticChange]:
    """Return copies of ``changes`` with ``verdict`` and ``rules_fired`` populated.

    The differ deliberately does not set these: it describes *what* changed, and this
    module rules on *whether it matters*. Keeping the two apart is what allows the same
    diff to be re-ruled under a different framework without re-diffing.
    """
    out: list[SemanticChange] = []
    for change in changes:
        result = evaluate_change(change, context)
        # model_copy does not validate, so the type here has to be right at the source:
        # SemanticChange.rules_fired is a tuple, and handing it a list produces a
        # serializer warning on every CI run.
        out.append(
            change.model_copy(
                update={"verdict": result.verdict, "rules_fired": tuple(result.rules_fired)}
            )
        )
    return out


@dataclass(frozen=True)
class DiffAssessment:
    """Whole-release verdict, and what it means for approvals."""

    changes: tuple[SemanticChange, ...]
    verdict: Materiality
    accreditation_impact: AccreditationImpact
    material_count: int
    review_count: int
    immaterial_count: int
    rules_fired: tuple[str, ...]
    headline: str


def assess_diff(diff: ReleaseDiff, context: MaterialityContext | None = None) -> DiffAssessment:
    """Rule on a whole release.

    The mapping from verdict to accreditation consequence is the product's central
    claim, so it lives in one place:

    * any material change      -> the approval is SUSPENDED
    * any needs-review change  -> the approval REQUIRES REVALIDATION
    * otherwise                -> the approval stands, the baseline advances
    """
    ruled = apply_verdicts(diff.changes, context)

    material = [c for c in ruled if c.verdict is Materiality.MATERIAL]
    review = [c for c in ruled if c.verdict is Materiality.NEEDS_REVIEW]
    immaterial = [c for c in ruled if c.verdict is Materiality.IMMATERIAL]

    if material:
        verdict = Materiality.MATERIAL
        impact = AccreditationImpact.SUSPENDS
        headline = (
            f"{len(material)} material change"
            f"{'s' if len(material) != 1 else ''} — the approval is suspended"
        )
    elif review:
        verdict = Materiality.NEEDS_REVIEW
        impact = AccreditationImpact.REQUIRES_REVALIDATION
        headline = (
            f"{len(review)} change{'s' if len(review) != 1 else ''} need adjudication "
            "before the approval can stand"
        )
    else:
        verdict = Materiality.IMMATERIAL
        impact = AccreditationImpact.NONE
        headline = (
            "No material change — the approval stands and the baseline advances"
            if ruled
            else "No changes detected"
        )

    # Deduplicated but order-stable, so the console can render rule chips in the order
    # they were reasoned about rather than alphabetically.
    seen: dict[str, None] = {}
    for change in ruled:
        for rule_id in change.rules_fired:
            seen.setdefault(rule_id, None)

    return DiffAssessment(
        changes=tuple(ruled),
        verdict=verdict,
        accreditation_impact=impact,
        material_count=len(material),
        review_count=len(review),
        immaterial_count=len(immaterial),
        rules_fired=tuple(seen),
        headline=headline,
    )


def describe_rule(rule_id: str) -> Rule | None:
    """Look up a rule so the console can explain a stored verdict.

    Verdicts persist, rule sets evolve. A release ruled last quarter must still be
    explainable, which is why ``release_changes.rules_fired`` stores ids and this
    resolves them rather than re-evaluating.
    """
    return RULES_BY_ID.get(rule_id)


def rule_catalogue() -> list[Rule]:
    """The whole rule set, for the settings screen and the accreditation pack.

    A customer asked to accept automated suspension wants to read the rules first.
    """
    return [*MATERIAL_RULES, *REVIEW_RULES, *IMMATERIAL_RULES, RULE_UNCLASSIFIED]


__all__ = [
    "ALL_RULES",
    "IMMATERIAL_RULES",
    "MATERIAL_RULES",
    "REVIEW_RULES",
    "RULES_BY_ID",
    "RULE_NO_IMPACT",
    "RULE_UNCLASSIFIED",
    "ChangeVerdict",
    "DiffAssessment",
    "MaterialityContext",
    "Rule",
    "apply_verdicts",
    "assess_diff",
    "describe_rule",
    "evaluate_change",
    "rule_catalogue",
]
