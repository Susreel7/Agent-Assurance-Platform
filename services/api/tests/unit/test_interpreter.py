"""Deterministic review brief — templates, ordering, and auditability."""

from __future__ import annotations

from app.domains.materiality.rules import apply_verdicts, describe_rule
from app.domains.releases.differ import diff_descriptors
from app.domains.releases.interpreter import brief_paths, build_review_brief, sentence_from_change
from app.domains.releases.schemas import Materiality


def _baseline(**composition: object) -> dict[str, object]:
    base: dict[str, object] = {
        "aap_version": "0.1",
        "agent": {"urn": "urn:aap:acme:x:y", "version": "1.0.0", "lifecycle_state": "production"},
        "runtime": {"autonomy": "supervised"},
        "models": [
            {
                "provider": "anthropic",
                "family": "claude",
                "id": "claude-sonnet-4-5",
                "endpoint_region": "eu-west-1",
                "role": "primary",
            }
        ],
        "data": {"classes": ["customer_pii"], "retention_days": 30},
    }
    if composition:
        base["composition"] = composition
    return base


def test_brief_sentences_carry_rule_ids() -> None:
    after = {**_baseline(), "runtime": {"autonomy": "autonomous"}}
    diff = diff_descriptors(_baseline(), after)
    ruled = apply_verdicts(diff.changes)
    brief = build_review_brief(
        diff.model_copy(update={"changes": ruled}),
        descriptor_digest="sha256:" + "a" * 64,
    )
    assert brief.re_accreditation
    for sentence in (
        *brief.re_accreditation,
        *brief.needs_review,
        *brief.informational,
    ):
        assert sentence.rule_ids
        assert describe_rule(sentence.rule_ids[0]) is not None


def test_material_changes_surface_first() -> None:
    after = {**_baseline(), "runtime": {"autonomy": "autonomous"}}
    after["data"] = {"classes": ["customer_pii"], "retention_days": 7}
    diff = diff_descriptors(_baseline(), after)
    ruled = apply_verdicts(diff.changes)
    brief = build_review_brief(
        diff.model_copy(update={"changes": ruled}),
        descriptor_digest="sha256:" + "b" * 64,
    )
    assert brief.re_accreditation
    assert all(s.materiality is Materiality.MATERIAL for s in brief.re_accreditation)
    assert brief.headline.startswith("Re-accreditation required")


def test_brief_paths_subset_of_diff() -> None:
    after = {**_baseline(), "runtime": {"autonomy": "semi_autonomous"}}
    diff = diff_descriptors(_baseline(), after)
    ruled = apply_verdicts(diff.changes)
    brief = build_review_brief(
        diff.model_copy(update={"changes": ruled}),
        descriptor_digest="sha256:" + "c" * 64,
    )
    diff_paths = {c.path for c in ruled}
    assert brief_paths(brief) <= diff_paths


def test_sentence_from_change_uses_summary_not_invented_facts() -> None:
    after = {**_baseline(), "runtime": {"autonomy": "autonomous"}}
    change = apply_verdicts(diff_descriptors(_baseline(), after).changes)[0]
    sentence = sentence_from_change(change)
    assert change.summary.split(".")[0] in sentence.text or "autonomy" in sentence.text.lower()
