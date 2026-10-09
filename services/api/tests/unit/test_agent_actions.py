"""The action ledger: what the envelope refuses, and whether it still agrees with SQL.

Three kinds of test.

The first compares every vocabulary in ``app/domains/agent_actions/schemas.py`` against
the CHECK constraint that spells the same list out in `0023` or `0024`. This is the only
place that can see both. It exists because the drift has already happened once here —
D-057, the audit ``category`` vocabulary, where four of seven values failed at INSERT and
the trail looked healthy while one subsystem's history silently never landed.

The second pins content-freedom as a property of the declarations rather than of review:
no column on the ledger and no field in the envelope may be named like a prompt, a
completion, a command line or a file body, and the facet map must refuse a key it does
not know.

The third pins the cross-field rules — an enforcing outcome needs a grade that could have
enforced, a downstream reference needs its kind — each of which has a twin CHECK in
`0024` because the table is reachable by backfill as well as by HTTP.

The append-only trigger, RLS and partition routing are database behaviour and are
asserted in `tests/sql/invariants.sql` against a real Postgres.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.db.models.agent_actions import AgentAction, AgentActionReceipt
from app.db.models.agent_runtime import AgentInstance, AgentSession, AgentTask, Delegation
from app.domains.agent_actions.schemas import (
    MAX_FACET_ARRAY_ITEMS,
    MAX_FACET_BYTES,
    MAX_FACET_ITEM_CHARS,
    MAX_FACET_TEXT_CHARS,
    SCHEMA_ID,
    ActionEnvelope,
    ActionOutcome,
    CapabilityKind,
    DataClass,
    DestinationClass,
    DownstreamMutationKind,
    EnforcementGrade,
    Harness,
    ResourceClass,
    ResourceKind,
    RiskClass,
    RiskSignal,
    RootHumanBasis,
    SessionTaint,
    effective_enforcement_grade,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
IDENTITY_MIGRATION = _VERSIONS / "0023_agent_runtime_identity.py"
LEDGER_MIGRATION = _VERSIONS / "0024_agent_actions_ledger.py"


def _vocabulary(source: str, constraint: str) -> set[str]:
    """Pull the literal list out of one named CHECK constraint.

    Handles both spellings the migrations use: ``col IN ('a', 'b')`` for a scalar and
    ``col <@ ARRAY['a', 'b']`` for an array column.
    """
    start = source.find(constraint)
    assert start != -1, f"{constraint} is no longer in the migration this test reads"
    window = source[start : start + 2000]
    match = re.search(r"(?:IN \(|<@ ARRAY\[)(.*?)(?:\)|\])", window, re.S)
    assert match is not None, f"{constraint} no longer has the shape this test parses"
    return set(re.findall(r"'([A-Za-z0-9_.]+)'", match.group(1)))


def _envelope(**overrides: Any) -> ActionEnvelope:
    payload: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "event_id": str(uuid4()),
        "occurred_at": "2026-09-22T11:00:00+00:00",
        "environment": "production",
        "subject": {
            "human_member_id": str(uuid4()),
            "root_human_basis": "triggered_by",
        },
        "capability": {"kind": "shell.exec", "operation": "exec"},
        "decision": {"outcome": "observed", "enforcement_grade": "D"},
        "provenance": {
            "collector_id": "cursor-hook",
            "collector_version": "0.1.0",
            "event_hash": "sha256:" + "a" * 64,
        },
    }
    payload.update(overrides)
    return ActionEnvelope.model_validate(payload)


# ---- the two vocabularies are one vocabulary ------------------------------------------


@pytest.mark.parametrize(
    ("constraint", "enum"),
    [
        ("agent_actions_capability_kind_valid", CapabilityKind),
        ("agent_actions_outcome_valid", ActionOutcome),
        ("agent_actions_grade_valid", EnforcementGrade),
        ("agent_actions_root_basis_valid", RootHumanBasis),
        ("agent_actions_resource_kind_valid", ResourceKind),
        ("agent_actions_resource_class_valid", ResourceClass),
        ("agent_actions_destination_class_valid", DestinationClass),
        ("agent_actions_risk_class_valid", RiskClass),
        ("agent_actions_taint_valid", SessionTaint),
        ("agent_actions_source_harness_valid", Harness),
        ("agent_actions_downstream_kind_valid", DownstreamMutationKind),
        ("agent_actions_data_classes_known", DataClass),
        ("agent_actions_risk_signals_known", RiskSignal),
    ],
)
def test_every_ledger_vocabulary_matches_its_check_constraint(
    constraint: str, enum: type[Any]
) -> None:
    source = LEDGER_MIGRATION.read_text(encoding="utf-8")
    assert _vocabulary(source, constraint) == {member.value for member in enum}


def test_the_harness_list_is_the_same_in_the_fleet_view_and_the_ledger() -> None:
    """`0023` and `0024` both spell it out, and the API is the third copy.

    Two vocabularies for one fact is how a fleet view and a ledger view come to disagree
    about which harnesses exist in the estate — one screen reporting six harnesses and
    another seven, with no way to tell which is wrong.
    """
    in_instances = _vocabulary(
        IDENTITY_MIGRATION.read_text(encoding="utf-8"), "agent_instances_harness_valid"
    )
    in_ledger = _vocabulary(
        LEDGER_MIGRATION.read_text(encoding="utf-8"), "agent_actions_source_harness_valid"
    )
    assert in_instances == in_ledger == {member.value for member in Harness}


def test_the_session_taint_vocabulary_is_the_same_on_both_tables() -> None:
    """``agent_sessions.taint`` is the source; ``agent_actions.session_taint`` copies it."""
    on_session = _vocabulary(
        IDENTITY_MIGRATION.read_text(encoding="utf-8"), "agent_sessions_taint_valid"
    )
    assert on_session == {member.value for member in SessionTaint}


def test_the_facet_allow_list_matches_the_database_validator() -> None:
    """``agent_action_facets_valid()`` and the boundary allow-list are one list.

    A key the boundary permits and the function rejects is a 500 from inside a batch; a
    key the function permits and the boundary rejects is a facet nobody can send. Both
    are silent until a specific capability kind happens to use that key.
    """
    from app.domains.agent_actions.schemas import (
        FACET_ARRAY_KEYS,
        FACET_NUMBER_KEYS,
        FACET_TEXT_KEYS,
    )

    source = LEDGER_MIGRATION.read_text(encoding="utf-8")
    for declaration, expected in (
        ("text_keys constant text[] := ARRAY[", FACET_TEXT_KEYS),
        ("number_keys constant text[] := ARRAY[", FACET_NUMBER_KEYS),
        ("array_keys constant text[] := ARRAY[", FACET_ARRAY_KEYS),
    ):
        start = source.find(declaration)
        assert start != -1, f"{declaration!r} is no longer in 0024"
        body = source[start + len(declaration) : source.index("]", start + len(declaration))]
        assert set(re.findall(r"'([a-z0-9_]+)'", body)) == expected


def test_the_facet_bound_is_slacker_in_the_database_than_at_the_boundary() -> None:
    """Deliberate, and the direction matters.

    Pydantic measures compact JSON; ``pg_column_size`` measures jsonb's binary layout.
    Equal numbers would make some records fail in Postgres after passing validation, so a
    rejection would arrive as a constraint violation from the middle of a batch rather
    than as a 422 that names the field.
    """
    source = LEDGER_MIGRATION.read_text(encoding="utf-8")
    match = re.search(r"pg_column_size\(argument_facets\) <= (\d+)", source)
    assert match is not None, "the facet size CHECK is no longer where this test looks"
    assert int(match.group(1)) > MAX_FACET_BYTES


# ---- content-freedom is a property of the declarations --------------------------------

# Names that would mean the ledger had started holding the thing it exists not to hold.
# `argument_digest`, `argument_facets` and `intent_digest` are the sanctioned bounded
# forms and are deliberately not matched: a digest is not content, and the facet map is
# allow-listed by `agent_action_facets_valid`.
_CONTENT_SHAPED = re.compile(
    r"(prompt|completion|argv|command_line|commandline|stdout|stderr|"
    r"payload|file_body|file_content|body|snippet|transcript|raw_)"
)

_LEDGER_MODELS = (
    AgentAction,
    AgentActionReceipt,
    AgentInstance,
    AgentSession,
    AgentTask,
    Delegation,
)


@pytest.mark.parametrize("model", _LEDGER_MODELS, ids=lambda m: str(m.__tablename__))
def test_no_ledger_table_has_a_content_shaped_column(model: type[Any]) -> None:
    """The schema-level answer to "prove you don't store our code" (`design/17` §8, 24).

    Asserted rather than left to review because the failure mode is additive: nobody
    removes content-freedom, somebody adds one convenient column to one table and the
    claim is quietly no longer true.
    """
    offending = [c.name for c in model.__table__.columns if _CONTENT_SHAPED.search(c.name)]
    assert not offending, f"{model.__tablename__} has content-shaped column(s): {offending}"


def _field_names(model: type[BaseModel], seen: set[type[BaseModel]] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names |= _field_names(annotation, seen)
    return names


def test_the_envelope_has_no_content_shaped_field() -> None:
    offending = sorted(n for n in _field_names(ActionEnvelope) if _CONTENT_SHAPED.search(n))
    assert not offending, f"aap.action.v1 has content-shaped field(s): {offending}"


def test_the_envelope_rejects_a_field_it_does_not_know() -> None:
    """``extra="forbid"`` is the privacy control, not a strictness preference.

    Silently dropping ``prompt`` would be safe for storage and useless as an answer to a
    security review, because nobody can see a field that was quietly discarded.
    """
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _envelope(prompt="summarise the customer's medical history")


def test_the_envelope_rejects_the_two_fields_deliberately_left_out_of_the_mvp() -> None:
    """``payload_ref`` has no resolver, and collector signing keys are V1.

    Both are in `design/15` §9 and neither is in `0024`. Accepting them would mean a
    collector believing it had sent a pointer we can resolve and a signature we check.
    """
    with pytest.raises(ValidationError):
        _envelope(arguments={"payload_ref": "cust://blob/1"})
    with pytest.raises(ValidationError):
        _envelope(
            provenance={
                "collector_id": "cursor-hook",
                "collector_version": "0.1.0",
                "event_hash": "a" * 64,
                "signature": "deadbeef",
            }
        )


def test_facets_reject_a_key_outside_the_allow_list() -> None:
    with pytest.raises(ValidationError, match="not in the allow-list"):
        _envelope(arguments={"facets": {"full_command": "curl https://evil.test"}})


def test_facets_reject_a_full_path_smuggled_through_path_roots() -> None:
    """``path_roots`` is roots — ``/etc``, ``~/.aws`` — so the item bound is short."""
    with pytest.raises(ValidationError, match="longer than"):
        _envelope(arguments={"facets": {"path_roots": ["/" + "a" * (MAX_FACET_ITEM_CHARS + 1)]}})


def test_facets_reject_an_over_long_text_value() -> None:
    with pytest.raises(ValidationError, match="longer than"):
        _envelope(arguments={"facets": {"host": "h" * (MAX_FACET_TEXT_CHARS + 1)}})


def test_facets_reject_too_many_array_items() -> None:
    flags = [f"--f{i}" for i in range(MAX_FACET_ARRAY_ITEMS + 1)]
    with pytest.raises(ValidationError, match="more than"):
        _envelope(arguments={"facets": {"argv_flags": flags}})


def test_facets_reject_a_payload_that_is_small_in_every_field_but_large_overall() -> None:
    """Every individual bound satisfied, and the whole map still a payload.

    Five allow-listed array keys at thirty-two items of sixty-four characters passes each
    per-field check and is several kilobytes of facet map, which is the shape this bound
    exists for.
    """
    item = "x" * MAX_FACET_ITEM_CHARS
    facets = {
        key: [item] * MAX_FACET_ARRAY_ITEMS
        for key in ("argv_flags", "path_roots", "path_classes", "sql_verbs", "sql_tables")
    }
    with pytest.raises(ValidationError, match=r"over the \d+ limit"):
        _envelope(arguments={"facets": facets})


def test_facets_accept_the_classifications_they_are_for() -> None:
    """The permitted shape, stated positively so the bounds above cannot creep inward."""
    envelope = _envelope(
        arguments={
            "digest": "sha256:" + "b" * 64,
            "facets": {
                "binary": "curl",
                "method": "POST",
                "host": "backboard.railway.app",
                "argv_count": 6,
                "argv_flags": ["-X", "--data-binary"],
                "path_roots": ["~/.aws"],
                "sql_verbs": [],
            },
            "truncated": False,
        }
    )
    assert envelope.arguments.facets["binary"] == "curl"


# ---- an enforcement claim has to be one ------------------------------------------------


def test_unknown_reads_as_e() -> None:
    """There is no code path in which ``unknown`` counts as protection.

    The Python twin of SQL ``effective_enforcement_grade()``. A coverage number computed
    from the raw column instead would put the population we cannot see into the protected
    half, which is the one direction the mistake must never go.
    """
    assert effective_enforcement_grade(EnforcementGrade.UNKNOWN) is EnforcementGrade.E
    assert effective_enforcement_grade(None) is EnforcementGrade.E
    assert effective_enforcement_grade("B") is EnforcementGrade.B
    assert _envelope().decision.effective_grade is EnforcementGrade.D


def test_a_grade_is_mandatory() -> None:
    with pytest.raises(ValidationError):
        _envelope(decision={"outcome": "observed"})


@pytest.mark.parametrize("grade", ["E", "unknown"])
def test_an_enforcing_outcome_at_grade_e_is_refused(grade: str) -> None:
    """E means not covered, so nothing can have refused, masked or rerouted it.

    This is the check that stops the console showing protection that did not happen.
    """
    with pytest.raises(ValidationError, match="means not covered"):
        _envelope(decision={"outcome": "deny", "enforcement_grade": grade})


def test_a_denial_at_grade_d_is_still_recordable() -> None:
    """Deliberately allowed, and the reasoning is in `0024`.

    D is "observed afterwards". A vendor control that denied something before we heard
    about it is a real denial we did not perform — the grade already says so, and losing
    the row would be worse than recording it honestly.
    """
    envelope = _envelope(decision={"outcome": "deny", "enforcement_grade": "D"})
    assert envelope.decision.outcome is ActionOutcome.DENY


def test_observed_is_not_allow() -> None:
    """The MVP ledger is read-only, so most rows record a decision nobody took.

    Folding ``observed`` into ``allow`` would claim a permission decision we never made,
    and every coverage number computed from the column would then be a lie in our favour.
    """
    assert ActionOutcome.OBSERVED != ActionOutcome.ALLOW
    assert ActionOutcome.OBSERVED not in (ActionOutcome.ALLOW, ActionOutcome.ANNOTATE)


# ---- identity and joins ---------------------------------------------------------------


def test_an_action_without_a_human_root_is_refused() -> None:
    """`design/14` §1. An action nobody can be asked about is not evidence."""
    with pytest.raises(ValidationError):
        _envelope(subject={"root_human_basis": "triggered_by"})


def test_an_action_by_an_unregistered_agent_is_accepted() -> None:
    """Discovery must never block (`design/14` §9).

    The asymmetry with the human root is the point: a shadow agent is one of the things
    the ledger exists to surface, so a missing ``agent_id`` is a finding rather than an
    error.
    """
    envelope = _envelope()
    assert envelope.subject.agent_id is None


def test_delegation_depth_must_agree_with_parentage() -> None:
    """Depth and parentage are one fact stored twice, so they have to agree."""
    with pytest.raises(ValidationError, match="delegation_depth"):
        _envelope(
            subject={
                "human_member_id": str(uuid4()),
                "root_human_basis": "triggered_by",
                "delegation_depth": 3,
            }
        )


def test_a_downstream_reference_needs_its_kind() -> None:
    """A reference with no kind is unjoinable; a kind with no reference is a rumour."""
    with pytest.raises(ValidationError, match="downstream_mutation"):
        _envelope(outcome={"downstream_mutation_ref": "9f2c1ab"})
    with pytest.raises(ValidationError, match="downstream_mutation"):
        _envelope(outcome={"downstream_mutation_kind": "commit"})

    envelope = _envelope(
        outcome={"downstream_mutation_kind": "commit", "downstream_mutation_ref": "9f2c1ab"}
    )
    assert envelope.outcome.downstream_mutation_kind is DownstreamMutationKind.COMMIT


# ---- shape ------------------------------------------------------------------------------


def test_a_naive_timestamp_is_refused() -> None:
    """``occurred_at`` decides the partition a row lands in.

    Interpreting a naive value against the server's zone silently moves an action between
    months for anybody not in UTC, and retention is written in months.
    """
    with pytest.raises(ValidationError, match="UTC offset"):
        _envelope(occurred_at="2026-09-22T11:00:00")


def test_a_digest_is_accepted_with_or_without_the_sha256_prefix() -> None:
    """`design/15` writes ``sha256:<hex>``; `0017` and `0018` write bare hex.

    Both spellings are in the design documents a collector author will read, so both are
    accepted and normalised. Rejecting one would be a compatibility break over
    punctuation.
    """
    assert _envelope().provenance.event_hash == "a" * 64
    prefixed = _envelope(
        provenance={
            "collector_id": "cursor-hook",
            "collector_version": "0.1.0",
            "event_hash": "SHA256:" + "A" * 64,
        }
    )
    assert prefixed.provenance.event_hash == "a" * 64


def test_a_truncated_digest_is_refused() -> None:
    with pytest.raises(ValidationError, match="64 hex characters"):
        _envelope(
            provenance={
                "collector_id": "cursor-hook",
                "collector_version": "0.1.0",
                "event_hash": "abc123",
            }
        )


@pytest.mark.parametrize(
    "operation",
    ["curl -X POST https://evil.test", "Exec", "/bin/sh", "", "x" * 65],
)
def test_the_operation_is_a_verb_and_cannot_carry_a_command_line(operation: str) -> None:
    """Short, lower-cased and shaped, so the open verb space cannot become an argv dump."""
    with pytest.raises(ValidationError):
        _envelope(capability={"kind": "shell.exec", "operation": operation})


def test_the_schema_identifier_is_pinned() -> None:
    """A collector sending a version we do not know must be refused, not half-read."""
    with pytest.raises(ValidationError):
        _envelope(schema="aap.action.v2")


# ---- one head ---------------------------------------------------------------------------


def test_the_migration_history_has_exactly_one_head() -> None:
    """`inv_single_alembic_head`. Two heads is a database nobody can upgrade.

    Cheap to check and easy to reach: two agents adding a revision against the same
    ``down_revision`` produces a branch that only shows up when somebody runs the
    upgrade.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    heads = list(ScriptDirectory.from_config(config).get_heads())
    assert heads == ["0024_agent_actions_ledger"], f"expected one head, found {heads}"
