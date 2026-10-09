"""Semantic descriptor diff.

This is the engine behind the release view. Given two AAP descriptors it produces typed,
human-readable changes rather than a text diff.

Design notes worth keeping in mind when extending this:

* Every extractor returns a *stable identity* per item so that "modified" can be
  distinguished from "removed plus added". Getting this wrong makes a model version bump
  look like a model replacement, which is the difference between an immaterial change and
  a suspended accreditation.
* Summaries are written as complete sentences, not as ``field: a -> b``. The whole point
  is legibility to someone who did not write the change.
* ``detail`` explains the consequence. It is optional, but it is what turns a changelog
  into something a reviewer can act on without asking the author.
* Materiality is *not* decided here. The differ describes; the materiality engine judges.
  Keeping those separate is what allows per-framework and per-customer rule overrides.
"""

from __future__ import annotations

import json
from typing import Any

from app.domains.releases.schemas import (
    ChangeCategory,
    ChangeOperation,
    ImpactDimension,
    ReleaseDiff,
    SemanticChange,
    Severity,
)

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _get(d: dict[str, Any], path: str, default: Any = None) -> Any:
    """Dotted lookup that tolerates missing intermediate keys."""
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _fmt(value: Any) -> str:
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "none"
    return str(value)


def _index_by(items: list[dict[str, Any]] | None, key: str) -> dict[str, dict[str, Any]]:
    """Index a descriptor list by one of its fields, skipping entries that are not
    mappings.

    The skip is not defensive padding. This runs in the CI release gate against an
    uploaded descriptor, so a list holding a bare string instead of an object is
    reachable input. Raising here would fail the build with an ``AttributeError`` from
    the middle of the differ, which reads as a platform outage rather than as a
    malformed descriptor. Schema validation is what reports the shape problem; the
    differ's job is to survive long enough to let it.
    """
    return {
        str(i.get(key)): i for i in (items or []) if isinstance(i, dict) and i.get(key) is not None
    }


# --------------------------------------------------------------------------------------
# Field-level specifications
#
# Each entry says: where to look, what to call it, why a reader should care, and how
# serious it is. Adding a governed field is a one-line change here, which is the point.
# --------------------------------------------------------------------------------------

type FieldSpec = tuple[str, str, ChangeCategory, frozenset[ImpactDimension], Severity, str | None]

SCALAR_FIELDS: list[FieldSpec] = [
    # ---- inference parameters: invisible in a code diff, decisive for behaviour ----
    (
        "inference.temperature",
        "Sampling temperature",
        ChangeCategory.INFERENCE_PARAMS,
        frozenset({ImpactDimension.BEHAVIOUR}),
        Severity.MEDIUM,
        "Higher values make output less deterministic, which changes how reproducible "
        "the agent's decisions are and can invalidate prior evaluation results.",
    ),
    (
        "inference.top_p",
        "Nucleus sampling threshold",
        ChangeCategory.INFERENCE_PARAMS,
        frozenset({ImpactDimension.BEHAVIOUR}),
        Severity.LOW,
        None,
    ),
    (
        "inference.max_tokens",
        "Maximum output tokens",
        ChangeCategory.INFERENCE_PARAMS,
        frozenset({ImpactDimension.BEHAVIOUR, ImpactDimension.COST}),
        Severity.LOW,
        "Affects both per-call cost and whether long responses are truncated mid-task.",
    ),
    (
        "inference.seed",
        "Sampling seed",
        ChangeCategory.INFERENCE_PARAMS,
        frozenset({ImpactDimension.BEHAVIOUR}),
        Severity.LOW,
        None,
    ),
    # ---- resilience: the settings that decide how failure behaves ----
    (
        "resilience.request_timeout_ms",
        "Request timeout",
        ChangeCategory.RESILIENCE,
        frozenset({ImpactDimension.LATENCY, ImpactDimension.BEHAVIOUR}),
        Severity.MEDIUM,
        "A shorter timeout increases failures under load; a longer one increases the "
        "time a caller waits before a fallback engages.",
    ),
    (
        "resilience.max_retries",
        "Retry attempts",
        ChangeCategory.RESILIENCE,
        frozenset({ImpactDimension.LATENCY, ImpactDimension.COST}),
        Severity.MEDIUM,
        "Retries multiply cost and worst-case latency. With a non-idempotent tool they "
        "can also duplicate side effects.",
    ),
    (
        "resilience.backoff",
        "Retry backoff strategy",
        ChangeCategory.RESILIENCE,
        frozenset({ImpactDimension.LATENCY}),
        Severity.LOW,
        None,
    ),
    (
        "resilience.circuit_breaker.failure_threshold",
        "Circuit breaker threshold",
        ChangeCategory.RESILIENCE,
        frozenset({ImpactDimension.BEHAVIOUR}),
        Severity.MEDIUM,
        None,
    ),
    (
        "resilience.rate_limit.requests_per_minute",
        "Rate limit",
        ChangeCategory.RESILIENCE,
        frozenset({ImpactDimension.COST, ImpactDimension.LATENCY}),
        Severity.LOW,
        None,
    ),
    (
        "resilience.fallback_model",
        "Fallback model",
        ChangeCategory.RESILIENCE,
        frozenset({ImpactDimension.BEHAVIOUR, ImpactDimension.COMPLIANCE}),
        Severity.HIGH,
        "The fallback runs under the same approval as the primary, so it must satisfy "
        "the same residency and retention constraints.",
    ),
    # ---- residency and data ----
    (
        "data.residency.cross_border",
        "Cross-border transfer stance",
        ChangeCategory.RESIDENCY,
        frozenset({ImpactDimension.COMPLIANCE, ImpactDimension.SECURITY}),
        Severity.CRITICAL,
        None,
    ),
    (
        "data.retention_days",
        "Data retention window",
        ChangeCategory.RESIDENCY,
        frozenset({ImpactDimension.COMPLIANCE}),
        Severity.HIGH,
        None,
    ),
    # ---- deployment and runtime ----
    (
        "runtime.framework",
        "Agent framework",
        ChangeCategory.DEPLOYMENT,
        frozenset({ImpactDimension.BEHAVIOUR}),
        Severity.HIGH,
        None,
    ),
    (
        "runtime.framework_version",
        "Framework version",
        ChangeCategory.DEPLOYMENT,
        frozenset({ImpactDimension.BEHAVIOUR}),
        Severity.LOW,
        None,
    ),
    (
        "runtime.autonomy",
        "Autonomy level",
        ChangeCategory.OVERSIGHT,
        frozenset({ImpactDimension.SECURITY, ImpactDimension.COMPLIANCE}),
        Severity.CRITICAL,
        "Raising autonomy removes points at which a person could intervene.",
    ),
    (
        "agent.lifecycle_state",
        "Lifecycle state",
        ChangeCategory.DEPLOYMENT,
        frozenset({ImpactDimension.COMPLIANCE}),
        Severity.MEDIUM,
        None,
    ),
    # ---- security posture ----
    (
        "security.authentication",
        "Authentication method",
        ChangeCategory.GUARDRAIL,
        frozenset({ImpactDimension.SECURITY}),
        Severity.HIGH,
        None,
    ),
    (
        "security.secrets_source",
        "Secrets source",
        ChangeCategory.GUARDRAIL,
        frozenset({ImpactDimension.SECURITY}),
        Severity.MEDIUM,
        None,
    ),
    # ---- accountability ----
    (
        "accountability.accountable_person",
        "Accountable owner",
        ChangeCategory.METADATA,
        frozenset({ImpactDimension.COMPLIANCE}),
        Severity.MEDIUM,
        "Approvals reference the owner of record, so a handover has to be recorded.",
    ),
    (
        "accountability.owning_team",
        "Owning team",
        ChangeCategory.METADATA,
        frozenset({ImpactDimension.COMPLIANCE}),
        Severity.LOW,
        None,
    ),
]


# --------------------------------------------------------------------------------------
# The differ
# --------------------------------------------------------------------------------------


def diff_descriptors(before: dict[str, Any] | None, after: dict[str, Any]) -> ReleaseDiff:
    """Produce the semantic delta between two AAP descriptors.

    ``before`` is None for an agent's first version, in which case the result is empty —
    there is nothing to compare against and a first release is not a change.
    """
    to_semver = str(_get(after, "agent.version", "unknown"))

    if before is None:
        return ReleaseDiff(from_semver=None, to_semver=to_semver, changes=[])

    changes: list[SemanticChange] = []
    changes += _diff_scalars(before, after)
    changes += _diff_models(before, after)
    changes += _diff_prompts(before, after)
    changes += _diff_tools(before, after)
    changes += _diff_mcp_servers(before, after)
    changes += _diff_capabilities(before, after)
    changes += _diff_string_sets(before, after)
    changes += _diff_delegations(before, after)
    changes += _diff_guardrails(before, after)
    changes += _diff_composition(before, after)

    return ReleaseDiff(
        from_semver=str(_get(before, "agent.version", "unknown")),
        to_semver=to_semver,
        changes=changes,
    )


def _diff_scalars(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    for path, subject, category, impacts, severity, detail in SCALAR_FIELDS:
        old, new = _get(before, path), _get(after, path)
        if old == new:
            continue
        if old is None:
            op, sentence = ChangeOperation.ADDED, f"{subject} set to {_fmt(new)}."
        elif new is None:
            op, sentence = ChangeOperation.REMOVED, f"{subject} removed (was {_fmt(old)})."
        else:
            op = ChangeOperation.MODIFIED
            sentence = f"{subject} changed from {_fmt(old)} to {_fmt(new)}."
        out.append(
            SemanticChange(
                category=category,
                operation=op,
                path=path,
                subject=subject,
                before_value=old,
                after_value=new,
                summary=sentence,
                detail=detail,
                impacts=impacts,
                severity=severity,
            )
        )
    return out


def _model_label(m: dict[str, Any]) -> str:
    provider = m.get("provider", "unknown provider")
    ident = m.get("id") or m.get("family") or "unspecified model"
    return f"{provider}/{ident}"


def _diff_models(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    """Models are identified by their declared role, not by list position.

    Position-based identity would report a reordered list as a full replacement, which
    would suspend accreditations for no reason.
    """
    out: list[SemanticChange] = []
    old_by_role = _index_by(before.get("models"), "role")
    new_by_role = _index_by(after.get("models"), "role")

    for role in sorted(set(old_by_role) | set(new_by_role)):
        old, new = old_by_role.get(role), new_by_role.get(role)
        subject = f"{role.title()} model" if role else "Model"
        path = f"models[role={role}]"

        if old is None and new is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.MODEL,
                    operation=ChangeOperation.ADDED,
                    path=path,
                    subject=subject,
                    after_value=new,
                    summary=f"{subject} added: {_model_label(new)}.",
                    detail="A new model introduces its own provider terms, retention "
                    "policy and processing region, all of which need approval.",
                    impacts=frozenset(
                        {
                            ImpactDimension.BEHAVIOUR,
                            ImpactDimension.COMPLIANCE,
                            ImpactDimension.COST,
                        }
                    ),
                    severity=Severity.HIGH,
                )
            )
            continue

        if new is None and old is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.MODEL,
                    operation=ChangeOperation.REMOVED,
                    path=path,
                    subject=subject,
                    before_value=old,
                    summary=f"{subject} removed: {_model_label(old)}.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.MEDIUM,
                )
            )
            continue

        assert old is not None and new is not None

        # Attributes are reported individually, because provider, family and point
        # version carry very different weight.
        for attr, label, sev, impacts, detail in (
            (
                "provider",
                "provider",
                Severity.CRITICAL,
                frozenset(
                    {
                        ImpactDimension.COMPLIANCE,
                        ImpactDimension.SECURITY,
                        ImpactDimension.BEHAVIOUR,
                    }
                ),
                "A different provider means different data-processing terms, so the "
                "existing approval no longer describes where data goes.",
            ),
            (
                "family",
                "family",
                Severity.HIGH,
                frozenset({ImpactDimension.BEHAVIOUR, ImpactDimension.COST}),
                "Evaluation results do not transfer between model families.",
            ),
            (
                "id",
                "version",
                Severity.MEDIUM,
                frozenset({ImpactDimension.BEHAVIOUR}),
                None,
            ),
            (
                "hosting",
                "hosting mode",
                Severity.CRITICAL,
                frozenset({ImpactDimension.COMPLIANCE, ImpactDimension.SECURITY}),
                "Moving between a vendor API, a managed cloud endpoint and self-hosting "
                "changes the residency and retention posture entirely.",
            ),
            (
                "endpoint_region",
                "endpoint region",
                Severity.CRITICAL,
                frozenset({ImpactDimension.COMPLIANCE}),
                None,
            ),
            (
                "data_retention",
                "retention terms",
                Severity.HIGH,
                frozenset({ImpactDimension.COMPLIANCE}),
                None,
            ),
        ):
            if old.get(attr) == new.get(attr):
                continue
            out.append(
                SemanticChange(
                    category=ChangeCategory.MODEL,
                    operation=ChangeOperation.MODIFIED,
                    path=f"{path}.{attr}",
                    subject=f"{subject} {label}",
                    before_value=old.get(attr),
                    after_value=new.get(attr),
                    summary=(
                        f"{subject} {label} changed from "
                        f"{_fmt(old.get(attr))} to {_fmt(new.get(attr))}."
                    ),
                    detail=detail,
                    impacts=impacts,
                    severity=sev,
                )
            )
    return out


def _diff_prompts(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    """Prompt changes are reported by digest here.

    Semantic distance is computed later by the materiality engine, which owns the
    embedding model. The differ stays free of model dependencies so it can run in CI
    with no network access.
    """
    out: list[SemanticChange] = []
    old_prompts = _index_by(before.get("prompts"), "name")
    new_prompts = _index_by(after.get("prompts"), "name")

    for name in sorted(set(old_prompts) | set(new_prompts)):
        old, new = old_prompts.get(name), new_prompts.get(name)
        subject = f"Instruction '{name}'"

        if old is None and new is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.PROMPT,
                    operation=ChangeOperation.ADDED,
                    path=f"prompts[name={name}]",
                    subject=subject,
                    after_value={"digest": new.get("digest")},
                    summary=f"{subject} added.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.HIGH,
                )
            )
        elif new is None and old is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.PROMPT,
                    operation=ChangeOperation.REMOVED,
                    path=f"prompts[name={name}]",
                    subject=subject,
                    before_value={"digest": old.get("digest")},
                    summary=f"{subject} removed.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.HIGH,
                )
            )
        elif old is not None and new is not None and old.get("digest") != new.get("digest"):
            out.append(
                SemanticChange(
                    category=ChangeCategory.PROMPT,
                    operation=ChangeOperation.MODIFIED,
                    path=f"prompts[name={name}].digest",
                    subject=subject,
                    before_value={"digest": old.get("digest")},
                    after_value={"digest": new.get("digest")},
                    summary=f"{subject} was edited.",
                    detail="Semantic distance is measured during materiality assessment; "
                    "reformatting scores near zero while an inverted condition scores high.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.MEDIUM,
                )
            )
    return out


def _diff_tools(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    old_tools = _index_by(before.get("tools"), "name")
    new_tools = _index_by(after.get("tools"), "name")

    for name in sorted(set(old_tools) | set(new_tools)):
        old, new = old_tools.get(name), new_tools.get(name)

        if old is None and new is not None:
            effect = new.get("effect", "unknown")
            reversible = new.get("reversible")
            writes = effect == "write"
            irreversible = reversible is False
            out.append(
                SemanticChange(
                    category=ChangeCategory.TOOL,
                    operation=ChangeOperation.ADDED,
                    path=f"tools[name={name}]",
                    subject=f"Tool '{name}'",
                    after_value=new,
                    summary=(
                        f"Tool '{name}' added with {effect} access"
                        + (" and irreversible effects." if irreversible else ".")
                    ),
                    detail=(
                        "An irreversible write tool expands what the agent can do that "
                        "cannot be undone, which is the single most consequential kind "
                        "of change an agent can undergo."
                        if irreversible
                        else None
                    ),
                    impacts=frozenset(
                        {ImpactDimension.SECURITY, ImpactDimension.BEHAVIOUR}
                        | ({ImpactDimension.COMPLIANCE} if writes else set())
                    ),
                    severity=(
                        Severity.CRITICAL
                        if irreversible
                        else Severity.HIGH
                        if writes
                        else Severity.LOW
                    ),
                )
            )
        elif new is None and old is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.TOOL,
                    operation=ChangeOperation.REMOVED,
                    path=f"tools[name={name}]",
                    subject=f"Tool '{name}'",
                    before_value=old,
                    summary=f"Tool '{name}' removed.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.MEDIUM,
                )
            )
        elif old is not None and new is not None:
            if old.get("effect") != new.get("effect"):
                widened = old.get("effect") == "read" and new.get("effect") == "write"
                out.append(
                    SemanticChange(
                        category=ChangeCategory.TOOL,
                        operation=ChangeOperation.MODIFIED,
                        path=f"tools[name={name}].effect",
                        subject=f"Tool '{name}' access",
                        before_value=old.get("effect"),
                        after_value=new.get("effect"),
                        summary=(
                            f"Tool '{name}' access changed from "
                            f"{_fmt(old.get('effect'))} to {_fmt(new.get('effect'))}."
                        ),
                        detail="Read access became write access." if widened else None,
                        impacts=frozenset({ImpactDimension.SECURITY, ImpactDimension.COMPLIANCE}),
                        severity=Severity.CRITICAL if widened else Severity.HIGH,
                    )
                )
            if old.get("reversible") != new.get("reversible"):
                out.append(
                    SemanticChange(
                        category=ChangeCategory.TOOL,
                        operation=ChangeOperation.MODIFIED,
                        path=f"tools[name={name}].reversible",
                        subject=f"Tool '{name}' reversibility",
                        before_value=old.get("reversible"),
                        after_value=new.get("reversible"),
                        summary=(
                            f"Tool '{name}' is now "
                            f"{'reversible' if new.get('reversible') else 'irreversible'}."
                        ),
                        impacts=frozenset({ImpactDimension.SECURITY}),
                        severity=Severity.HIGH,
                    )
                )
            if old.get("endpoint") != new.get("endpoint"):
                out.append(
                    SemanticChange(
                        category=ChangeCategory.TOOL,
                        operation=ChangeOperation.MODIFIED,
                        path=f"tools[name={name}].endpoint",
                        subject=f"Tool '{name}' endpoint",
                        before_value=old.get("endpoint"),
                        after_value=new.get("endpoint"),
                        summary=f"Tool '{name}' now points at a different endpoint.",
                        detail="A changed endpoint can move processing to another region "
                        "or another operator without any code change.",
                        impacts=frozenset({ImpactDimension.SECURITY, ImpactDimension.COMPLIANCE}),
                        severity=Severity.HIGH,
                    )
                )
    return out


def _diff_mcp_servers(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    old_srv = _index_by(_get(before, "references.mcp_servers"), "url")
    new_srv = _index_by(_get(after, "references.mcp_servers"), "url")

    for url in sorted(set(old_srv) | set(new_srv)):
        old, new = old_srv.get(url), new_srv.get(url)
        if old is None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.MCP_SERVER,
                    operation=ChangeOperation.ADDED,
                    path=f"references.mcp_servers[url={url}]",
                    subject="MCP server",
                    after_value=new,
                    summary=f"MCP server added: {url}.",
                    detail="An MCP server supplies its own tool list, so adding one can "
                    "expand the agent's capability surface without any change to the "
                    "agent's own code.",
                    impacts=frozenset({ImpactDimension.SECURITY, ImpactDimension.BEHAVIOUR}),
                    severity=Severity.HIGH,
                )
            )
        elif new is None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.MCP_SERVER,
                    operation=ChangeOperation.REMOVED,
                    path=f"references.mcp_servers[url={url}]",
                    subject="MCP server",
                    before_value=old,
                    summary=f"MCP server removed: {url}.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.MEDIUM,
                )
            )
        elif old.get("digest") != new.get("digest"):
            out.append(
                SemanticChange(
                    category=ChangeCategory.MCP_SERVER,
                    operation=ChangeOperation.MODIFIED,
                    path=f"references.mcp_servers[url={url}].digest",
                    subject="MCP server contents",
                    before_value=old.get("digest"),
                    after_value=new.get("digest"),
                    summary=f"MCP server {url} changed its advertised tools.",
                    detail="The server changed underneath the agent. Nothing in the "
                    "agent's own repository would show this.",
                    impacts=frozenset({ImpactDimension.SECURITY, ImpactDimension.BEHAVIOUR}),
                    severity=Severity.HIGH,
                )
            )
    return out


def _diff_capabilities(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    old_caps = _index_by(before.get("capabilities"), "name")
    new_caps = _index_by(after.get("capabilities"), "name")

    for name in sorted(set(old_caps) | set(new_caps)):
        old, new = old_caps.get(name), new_caps.get(name)

        if old is None and new is not None:
            irreversible = new.get("reversible") is False
            no_approval = new.get("human_approval") in (None, "none")
            out.append(
                SemanticChange(
                    category=ChangeCategory.CAPABILITY,
                    operation=ChangeOperation.ADDED,
                    path=f"capabilities[name={name}]",
                    subject=f"Capability '{name}'",
                    after_value=new,
                    summary=f"Capability '{name}' added.",
                    detail=(
                        "This capability is irreversible and requires no human approval."
                        if irreversible and no_approval
                        else None
                    ),
                    impacts=frozenset({ImpactDimension.SECURITY, ImpactDimension.COMPLIANCE}),
                    severity=Severity.CRITICAL if irreversible else Severity.HIGH,
                )
            )
        elif new is None and old is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.CAPABILITY,
                    operation=ChangeOperation.REMOVED,
                    path=f"capabilities[name={name}]",
                    subject=f"Capability '{name}'",
                    before_value=old,
                    summary=f"Capability '{name}' removed.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.LOW,
                )
            )
        elif old is not None and new is not None:
            ranks = {"required": 2, "conditional": 1, "none": 0, None: 0}
            old_app, new_app = old.get("human_approval"), new.get("human_approval")
            if old_app != new_app:
                weakened = ranks.get(new_app, 0) < ranks.get(old_app, 0)
                out.append(
                    SemanticChange(
                        category=ChangeCategory.OVERSIGHT,
                        operation=ChangeOperation.MODIFIED,
                        path=f"capabilities[name={name}].human_approval",
                        subject=f"Human approval for '{name}'",
                        before_value=old_app,
                        after_value=new_app,
                        summary=(
                            f"Human approval for '{name}' changed from "
                            f"{_fmt(old_app)} to {_fmt(new_app)}."
                        ),
                        detail=(
                            "Oversight was weakened. This removes a point at which a "
                            "person could have intervened."
                            if weakened
                            else None
                        ),
                        impacts=frozenset({ImpactDimension.SECURITY, ImpactDimension.COMPLIANCE}),
                        severity=Severity.CRITICAL if weakened else Severity.MEDIUM,
                    )
                )
            old_limit = (old.get("value_limit") or {}).get("max")
            new_limit = (new.get("value_limit") or {}).get("max")
            if old_limit != new_limit:
                raised = (new_limit or 0) > (old_limit or 0)
                out.append(
                    SemanticChange(
                        category=ChangeCategory.CAPABILITY,
                        operation=ChangeOperation.MODIFIED,
                        path=f"capabilities[name={name}].value_limit.max",
                        subject=f"Value limit for '{name}'",
                        before_value=old_limit,
                        after_value=new_limit,
                        summary=(
                            f"Value limit for '{name}' changed from "
                            f"{_fmt(old_limit)} to {_fmt(new_limit)}."
                        ),
                        detail="The ceiling on unattended financial exposure was raised."
                        if raised
                        else None,
                        impacts=frozenset({ImpactDimension.SECURITY}),
                        severity=Severity.HIGH if raised else Severity.LOW,
                    )
                )
    return out


# Sets of plain strings, where membership is the whole story.
STRING_SET_FIELDS: list[
    tuple[str, str, ChangeCategory, frozenset[ImpactDimension], Severity, str | None]
] = [
    (
        "data.classes",
        "Data class",
        ChangeCategory.DATA_CLASS,
        frozenset({ImpactDimension.COMPLIANCE, ImpactDimension.SECURITY}),
        Severity.CRITICAL,
        "The agent now handles a category of data it was not approved for.",
    ),
    (
        "data.special_categories",
        "Special-category data",
        ChangeCategory.DATA_CLASS,
        frozenset({ImpactDimension.COMPLIANCE}),
        Severity.CRITICAL,
        "Special-category data carries an elevated regulatory duty.",
    ),
    (
        "data.residency.permitted_regions",
        "Permitted region",
        ChangeCategory.RESIDENCY,
        frozenset({ImpactDimension.COMPLIANCE}),
        Severity.CRITICAL,
        None,
    ),
    (
        "security.network_egress",
        "Egress destination",
        ChangeCategory.GUARDRAIL,
        frozenset({ImpactDimension.SECURITY}),
        Severity.HIGH,
        None,
    ),
    (
        "security.prompt_injection_defences",
        "Injection defence",
        ChangeCategory.GUARDRAIL,
        frozenset({ImpactDimension.SECURITY}),
        Severity.HIGH,
        None,
    ),
]


def _diff_string_sets(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    for path, subject, category, impacts, severity, detail in STRING_SET_FIELDS:
        old = set(_get(before, path) or [])
        new = set(_get(after, path) or [])

        for item in sorted(new - old):
            out.append(
                SemanticChange(
                    category=category,
                    operation=ChangeOperation.ADDED,
                    path=f"{path}[{item}]",
                    subject=subject,
                    after_value=item,
                    summary=f"{subject} added: {item}.",
                    detail=detail,
                    impacts=impacts,
                    severity=severity,
                )
            )
        for item in sorted(old - new):
            # Removing a defence is serious; removing a data class is a reduction in
            # scope and therefore benign.
            removal_is_weakening = category is ChangeCategory.GUARDRAIL
            out.append(
                SemanticChange(
                    category=category,
                    operation=ChangeOperation.REMOVED,
                    path=f"{path}[{item}]",
                    subject=subject,
                    before_value=item,
                    summary=f"{subject} removed: {item}.",
                    detail="A protective control was removed." if removal_is_weakening else None,
                    impacts=impacts,
                    severity=severity if removal_is_weakening else Severity.LOW,
                )
            )
    return out


def _diff_delegations(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    old_del = _index_by(before.get("delegates_to"), "urn")
    new_del = _index_by(after.get("delegates_to"), "urn")

    for urn in sorted(set(old_del) | set(new_del)):
        old, new = old_del.get(urn), new_del.get(urn)
        if old is None and new is not None:
            untrusted = new.get("trust") not in ("internal_accredited", "internal")
            out.append(
                SemanticChange(
                    category=ChangeCategory.DELEGATION,
                    operation=ChangeOperation.ADDED,
                    path=f"delegates_to[urn={urn}]",
                    subject="Agent delegation",
                    after_value=new,
                    summary=f"Now delegates work to {urn}.",
                    detail="The trust boundary expanded to an agent that is not recorded "
                    "as internally accredited."
                    if untrusted
                    else "Anything the delegate can reach is now transitively reachable.",
                    impacts=frozenset({ImpactDimension.SECURITY, ImpactDimension.COMPLIANCE}),
                    severity=Severity.CRITICAL if untrusted else Severity.HIGH,
                )
            )
        elif new is None and old is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.DELEGATION,
                    operation=ChangeOperation.REMOVED,
                    path=f"delegates_to[urn={urn}]",
                    subject="Agent delegation",
                    before_value=old,
                    summary=f"No longer delegates work to {urn}.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.LOW,
                )
            )
    return out


def _diff_guardrails(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    """Data sources, which sit slightly apart from tools and deserve their own category."""
    out: list[SemanticChange] = []
    old_src = _index_by(_get(before, "data.sources"), "name")
    new_src = _index_by(_get(after, "data.sources"), "name")

    for name in sorted(set(old_src) | set(new_src)):
        old, new = old_src.get(name), new_src.get(name)
        if old is None and new is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.DATA_SOURCE,
                    operation=ChangeOperation.ADDED,
                    path=f"data.sources[name={name}]",
                    subject=f"Data source '{name}'",
                    after_value=new,
                    summary=(
                        f"Data source '{name}' added "
                        f"({_fmt(new.get('kind'))} in {_fmt(new.get('region'))})."
                    ),
                    impacts=frozenset({ImpactDimension.COMPLIANCE, ImpactDimension.SECURITY}),
                    severity=Severity.HIGH,
                )
            )
        elif new is None and old is not None:
            out.append(
                SemanticChange(
                    category=ChangeCategory.DATA_SOURCE,
                    operation=ChangeOperation.REMOVED,
                    path=f"data.sources[name={name}]",
                    subject=f"Data source '{name}'",
                    before_value=old,
                    summary=f"Data source '{name}' removed.",
                    impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                    severity=Severity.LOW,
                )
            )
        elif old is not None and new is not None and old.get("region") != new.get("region"):
            out.append(
                SemanticChange(
                    category=ChangeCategory.RESIDENCY,
                    operation=ChangeOperation.MODIFIED,
                    path=f"data.sources[name={name}].region",
                    subject=f"Data source '{name}' region",
                    before_value=old.get("region"),
                    after_value=new.get("region"),
                    summary=(
                        f"Data source '{name}' moved from "
                        f"{_fmt(old.get('region'))} to {_fmt(new.get('region'))}."
                    ),
                    impacts=frozenset({ImpactDimension.COMPLIANCE}),
                    severity=Severity.CRITICAL,
                )
            )
    return out


# --------------------------------------------------------------------------------------
# Composition block (optional) — identity-based, rename-aware
# --------------------------------------------------------------------------------------


def _item_fingerprint(item: dict[str, Any], *, exclude: str) -> str:
    """Stable content hash for rename pairing — ignores the identity field itself."""
    payload = {k: v for k, v in sorted(item.items()) if k != exclude}
    return json.dumps(payload, sort_keys=True, default=str)


def _pair_renames(
    removed: set[str],
    added: set[str],
    old_by_key: dict[str, dict[str, Any]],
    new_by_key: dict[str, dict[str, Any]],
    *,
    identity_field: str,
) -> tuple[set[str], set[str], list[tuple[str, str]]]:
    """Match removed+added rows with identical bodies but different identity keys."""
    still_removed = set(removed)
    still_added = set(added)
    pairs: list[tuple[str, str]] = []
    for old_key in list(still_removed):
        old_item = old_by_key[old_key]
        fp = _item_fingerprint(old_item, exclude=identity_field)
        candidates = [
            new_key
            for new_key in still_added
            if _item_fingerprint(new_by_key[new_key], exclude=identity_field) == fp
        ]
        if len(candidates) == 1:
            pairs.append((old_key, candidates[0]))
            still_removed.discard(old_key)
            still_added.discard(candidates[0])
    return still_removed, still_added, pairs


def _diff_indexed_composition(
    before_block: dict[str, Any],
    after_block: dict[str, Any],
    section: str,
    *,
    category: ChangeCategory,
    identity_field: str = "name",
    path_prefix: str | None = None,
    default_severity: Severity = Severity.MEDIUM,
    added_detail: str | None = None,
) -> list[SemanticChange]:
    """Diff one named list inside ``composition``."""
    prefix = path_prefix or f"composition.{section}"
    out: list[SemanticChange] = []
    old_items = _index_by(before_block.get(section), identity_field)
    new_items = _index_by(after_block.get(section), identity_field)
    all_keys = set(old_items) | set(new_items)
    removed = {k for k in all_keys if k in old_items and k not in new_items}
    added = {k for k in all_keys if k in new_items and k not in old_items}
    removed, added, renames = _pair_renames(
        removed, added, old_items, new_items, identity_field=identity_field
    )
    renamed_old = {p[0] for p in renames}
    renamed_new = {p[1] for p in renames}

    for old_key, new_key in renames:
        out.append(
            SemanticChange(
                category=category,
                operation=ChangeOperation.RENAMED,
                path=f"{prefix}[{identity_field}={old_key}→{new_key}]",
                subject=f"{section.replace('_', ' ').title()} '{old_key}'",
                before_value={identity_field: old_key, **old_items[old_key]},
                after_value={identity_field: new_key, **new_items[new_key]},
                summary=(
                    f"{section.replace('_', ' ').title()} '{old_key}' was renamed to '{new_key}'."
                ),
                impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                severity=Severity.LOW,
            )
        )

    for key in sorted(added):
        item = new_items[key]
        out.append(
            SemanticChange(
                category=category,
                operation=ChangeOperation.ADDED,
                path=f"{prefix}[{identity_field}={key}]",
                subject=f"{section.replace('_', ' ').title()} '{key}'",
                after_value=item,
                summary=f"A new {section.replace('_', ' ')} «{key}» was added to the agent.",
                detail=added_detail,
                impacts=frozenset({ImpactDimension.BEHAVIOUR, ImpactDimension.SECURITY}),
                severity=default_severity,
            )
        )

    for key in sorted(removed):
        item = old_items[key]
        out.append(
            SemanticChange(
                category=category,
                operation=ChangeOperation.REMOVED,
                path=f"{prefix}[{identity_field}={key}]",
                subject=f"{section.replace('_', ' ').title()} '{key}'",
                before_value=item,
                summary=f"{section.replace('_', ' ').title()} «{key}» was removed.",
                impacts=frozenset({ImpactDimension.BEHAVIOUR}),
                severity=Severity.MEDIUM,
            )
        )

    stable_keys = all_keys - removed - added - renamed_old - renamed_new
    for key in sorted(stable_keys):
        old, new = old_items.get(key), new_items.get(key)
        if old is None or new is None:
            continue
        for attr, label in (
            ("digest", "content digest"),
            ("path", "path"),
            ("ref", "reference"),
            ("trust", "trust level"),
            ("statement", "statement"),
            ("polarity", "polarity"),
            ("strength", "strength"),
            ("category", "category"),
            ("source_ref", "source"),
        ):
            if old.get(attr) == new.get(attr):
                continue
            out.append(
                SemanticChange(
                    category=category,
                    operation=ChangeOperation.MODIFIED,
                    path=f"{prefix}[{identity_field}={key}].{attr}",
                    subject=f"{section.replace('_', ' ').title()} '{key}' {label}",
                    before_value=old.get(attr),
                    after_value=new.get(attr),
                    summary=(
                        f"{section.replace('_', ' ').title()} «{key}» {label} changed "
                        f"from {_fmt(old.get(attr))} to {_fmt(new.get(attr))}."
                    ),
                    detail=(
                        "The impact of this attribute is not classified — it defaults to review."
                    ),
                    impacts=frozenset({ImpactDimension.BEHAVIOUR, ImpactDimension.COMPLIANCE}),
                    severity=Severity.HIGH,
                )
            )
    return out


def _diff_model_policy(
    before_block: dict[str, Any], after_block: dict[str, Any]
) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    old = before_block.get("model_policy")
    new = after_block.get("model_policy")
    if old == new:
        return out
    if not isinstance(old, dict) and isinstance(new, dict):
        out.append(
            SemanticChange(
                category=ChangeCategory.MODEL_POLICY,
                operation=ChangeOperation.ADDED,
                path="composition.model_policy",
                subject="Model policy",
                after_value=new,
                summary="A model routing policy was added.",
                impacts=frozenset({ImpactDimension.COMPLIANCE, ImpactDimension.BEHAVIOUR}),
                severity=Severity.HIGH,
            )
        )
        return out
    if isinstance(old, dict) and not isinstance(new, dict):
        out.append(
            SemanticChange(
                category=ChangeCategory.MODEL_POLICY,
                operation=ChangeOperation.REMOVED,
                path="composition.model_policy",
                subject="Model policy",
                before_value=old,
                summary="The model routing policy was removed.",
                impacts=frozenset({ImpactDimension.COMPLIANCE}),
                severity=Severity.HIGH,
            )
        )
        return out
    if not isinstance(old, dict) or not isinstance(new, dict):
        return out

    for attr in sorted(set(old) | set(new)):
        if old.get(attr) == new.get(attr):
            continue
        sev = Severity.CRITICAL if attr == "selection_mode" else Severity.HIGH
        out.append(
            SemanticChange(
                category=ChangeCategory.MODEL_POLICY,
                operation=ChangeOperation.MODIFIED,
                path=f"composition.model_policy.{attr}",
                subject=f"Model policy {attr.replace('_', ' ')}",
                before_value=old.get(attr),
                after_value=new.get(attr),
                summary=(
                    f"Model policy {attr.replace('_', ' ')} changed from "
                    f"{_fmt(old.get(attr))} to {_fmt(new.get(attr))}."
                ),
                detail=(
                    "Automatic model routing can send production data to models outside "
                    "the approved catalogue."
                    if attr == "selection_mode" and _fmt(new.get(attr)) == "auto"
                    else None
                ),
                impacts=frozenset({ImpactDimension.COMPLIANCE, ImpactDimension.BEHAVIOUR}),
                severity=sev,
            )
        )
    return out


def _diff_composition(before: dict[str, Any], after: dict[str, Any]) -> list[SemanticChange]:
    """Diff the optional ``composition`` block; absent blocks degrade to no changes."""
    old_block = before.get("composition")
    new_block = after.get("composition")
    if not isinstance(old_block, dict) and not isinstance(new_block, dict):
        return []
    old_block = old_block if isinstance(old_block, dict) else {}
    new_block = new_block if isinstance(new_block, dict) else {}

    out: list[SemanticChange] = []
    out += _diff_model_policy(old_block, new_block)
    out += _diff_indexed_composition(
        old_block,
        new_block,
        "rule_sources",
        category=ChangeCategory.RULE_SOURCE,
        default_severity=Severity.MEDIUM,
        added_detail="A new rule source may introduce obligations that were not reviewed.",
    )
    out += _diff_indexed_composition(
        old_block,
        new_block,
        "rule_obligations",
        category=ChangeCategory.RULE_OBLIGATION,
        identity_field="id",
        default_severity=Severity.HIGH,
        added_detail="New obligations change what the agent is allowed to do.",
    )
    out += _diff_indexed_composition(
        old_block,
        new_block,
        "skills",
        category=ChangeCategory.SKILL,
        default_severity=Severity.MEDIUM,
    )
    out += _diff_indexed_composition(
        old_block,
        new_block,
        "sub_agents",
        category=ChangeCategory.SUB_AGENT,
        default_severity=Severity.HIGH,
        added_detail="Sub-agents expand what the agent can delegate to.",
    )
    out += _diff_indexed_composition(
        old_block,
        new_block,
        "configs",
        category=ChangeCategory.CONFIG,
        default_severity=Severity.MEDIUM,
    )
    out += _diff_indexed_composition(
        old_block,
        new_block,
        "memory_retrieval",
        category=ChangeCategory.MEMORY_RETRIEVAL,
        default_severity=Severity.HIGH,
    )
    out += _diff_indexed_composition(
        old_block,
        new_block,
        "guardrails",
        category=ChangeCategory.GUARDRAIL,
        default_severity=Severity.HIGH,
    )
    return out
