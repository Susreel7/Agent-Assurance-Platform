"""The audit trail: what it accepts, and what it refuses to become.

Two kinds of test here. The first kind pins the boundary validation on `AuditRecord` —
mostly rule 5, keeping prompts and tool arguments out of a table nobody can redact after
the fact. The second kind compares the schema against migration 0017, because `category`
is spelled out in both places and nothing else checks that the two agree.

The append-only guarantee itself is a database trigger, so it is asserted in
`tests/sql/invariants.sql` against a real Postgres. What is checked here is that the
service offers no path that would want one: no update, no delete.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.security_audit import service
from app.domains.security_audit.schemas import (
    MAX_DETAIL_BYTES,
    MAX_DETAIL_KEYS,
    MAX_DETAIL_VALUE_CHARS,
    ActorKind,
    AuditRecord,
    Category,
    Outcome,
    Severity,
)

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0017_account_access_registry.py"
)


def _record(**overrides: object) -> AuditRecord:
    fields: dict[str, object] = {
        "event_type": "mcp.tool_call.denied",
        "category": Category.MCP,
        "outcome": Outcome.DENIED,
        "actor_kind": ActorKind.AGENT,
        "actor_label": "agent:claims-triage",
    }
    fields.update(overrides)
    return AuditRecord(**fields)


# ---- the trail has no mutation path ---------------------------------------------------


def test_the_service_exposes_no_way_to_change_history() -> None:
    """The absence is the guarantee, so it is asserted rather than left to be noticed.

    A trigger stops an UPDATE reaching the table; this stops a plausible-looking
    `amend_event` from being added next to `record` without anyone thinking about it.
    """
    offered = set(service.__all__)
    for forbidden in ("update", "amend", "delete", "redact", "purge", "correct"):
        assert not any(forbidden in name for name in offered), (
            f"security_audit.service exposes a '{forbidden}' path; the trail is append-only"
        )
    assert {"record", "record_many"} <= offered


def test_a_record_carries_no_caller_supplied_timestamp() -> None:
    """`occurred_at` is the partition key, and the database stamps it.

    Accepting one from the caller is how an append-only log gets rows written into last
    March, which is both a retention problem and a way to hide an event below the fold.
    """
    assert "occurred_at" not in AuditRecord.model_fields


# ---- rule 5: detail is a decision record, not a payload -------------------------------


def test_detail_rejects_a_nested_object() -> None:
    """Flat scalars only.

    Nesting is how a whole tool-call argument tree arrives in `detail` one commit after
    somebody decides a single nested field would be convenient.
    """
    with pytest.raises(ValidationError, match="must be a scalar"):
        _record(detail={"arguments": {"path": "/etc/passwd"}})


def test_detail_rejects_a_list() -> None:
    with pytest.raises(ValidationError, match="must be a scalar"):
        _record(detail={"tools": ["read_file", "write_file"]})


def test_detail_rejects_an_over_long_value() -> None:
    """The completion-shaped case: one key, one very long string."""
    with pytest.raises(ValidationError, match="longer than"):
        _record(detail={"model_output": "x" * (MAX_DETAIL_VALUE_CHARS + 1)})


def test_detail_rejects_too_many_keys() -> None:
    with pytest.raises(ValidationError, match="more than"):
        _record(detail={f"k{i}": i for i in range(MAX_DETAIL_KEYS + 1)})


def test_detail_rejects_a_payload_that_is_small_in_every_field_but_large_overall() -> None:
    """Per-value and per-key limits are both satisfiable while the row is still too big.

    Thirty-two keys of five hundred characters each passes both of the other checks and
    is eight kilobytes of audit row, which is the shape this bound exists for.
    """
    detail = {f"field_{i}": "x" * MAX_DETAIL_VALUE_CHARS for i in range(MAX_DETAIL_KEYS)}
    with pytest.raises(ValidationError, match=r"over the \d+ byte limit"):
        _record(detail=detail)


def test_detail_accepts_the_classifications_it_is_for() -> None:
    """The permitted shape, stated positively so the limits above cannot creep inward."""
    record = _record(
        detail={
            "capability": "read_file",
            "snapshot_digest": "a" * 64,
            "pinned": True,
            "risk_score": 0.92,
            "attempts": 3,
            "quarantined_at": None,
        }
    )
    assert record.detail["capability"] == "read_file"


def test_an_empty_detail_is_fine() -> None:
    """Most events are fully described by their typed columns."""
    assert _record().detail == {}


# ---- identifiers and digests ----------------------------------------------------------


@pytest.mark.parametrize(
    "event_type",
    ["MCP.Tool_Call", "mcp tool call", "1mcp.denied", "mcp/tool/denied", ""],
)
def test_event_type_is_a_dotted_lowercase_identifier(event_type: str) -> None:
    """Free-form event types make the trail unqueryable.

    `mcp.tool_call.denied` and `MCP tool call denied` describing the same thing means no
    filter ever returns all of it.
    """
    with pytest.raises(ValidationError):
        _record(event_type=event_type)


def test_event_type_accepts_the_dotted_form() -> None:
    assert _record(event_type="access.grant.revoked").event_type == "access.grant.revoked"


def test_policy_digest_must_be_a_full_sha256_in_hex() -> None:
    """A truncated or upper-case digest will not match the one the gateway recorded."""
    with pytest.raises(ValidationError):
        _record(policy_digest_hex="abc123")
    with pytest.raises(ValidationError):
        _record(policy_digest_hex="A" * 64)

    record = _record(policy_digest_hex="a" * 64)
    assert record.policy_digest_hex == "a" * 64


def test_actor_label_is_required_even_for_a_system_actor() -> None:
    """An event whose actor is blank is an event no one can be asked about."""
    with pytest.raises(ValidationError):
        _record(actor_kind=ActorKind.SYSTEM, actor_label="")


def test_severity_defaults_to_info_and_outcome_does_not() -> None:
    """Outcome is the one thing a producer must decide.

    Defaulting it would make "allowed" the value of every event whose writer forgot, and
    that is the direction that reads as a clean trail.
    """
    assert _record().severity is Severity.INFO
    with pytest.raises(ValidationError):
        AuditRecord(  # type: ignore[call-arg]
            event_type="access.grant.created",
            category=Category.ACCESS,
            actor_kind=ActorKind.MEMBER,
            actor_label="person:ana@example.com",
        )


# ---- schema and migration agree -------------------------------------------------------


def test_category_vocabulary_matches_the_database_check() -> None:
    """`category` is a text column with a CHECK, and the list is written out twice.

    This test exists because the two had already drifted: the CHECK allowed `registry`,
    `enforcement`, `payload` and `lifecycle` while the enum produced `mcp`, `routing`,
    `data` and `admin`, so four of the seven categories failed at INSERT — and only for
    the events that carried them, which is the worst way to find out.
    """
    source = MIGRATION.read_text(encoding="utf-8")
    match = re.search(
        r"security_audit_events_category_valid CHECK \(\s*category IN \(([^)]*)\)",
        source,
    )
    assert match is not None, "the category CHECK is no longer where this test looks"

    in_database = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    in_schema = {category.value for category in Category}
    assert in_database == in_schema


def test_the_detail_bound_is_slacker_in_the_database_than_at_the_boundary() -> None:
    """Deliberate, and the direction matters.

    The API measures compact JSON; the CHECK measures jsonb's binary layout. They are
    different quantities, so equal numbers would make some records fail in Postgres after
    passing validation. Slack in the other direction means a rejection is always a 422
    that names the field.
    """
    source = MIGRATION.read_text(encoding="utf-8")
    match = re.search(r"pg_column_size\(detail\) <= (\d+)", source)
    assert match is not None, "the detail CHECK is no longer where this test looks"
    assert int(match.group(1)) > MAX_DETAIL_BYTES


def test_digest_window_is_bounded() -> None:
    """The overview aggregate is computed live, so "all time" must not be askable."""
    assert service.DEFAULT_DIGEST_DAYS <= service.MAX_DIGEST_DAYS
    assert service.MAX_DIGEST_DAYS <= 90


def test_batch_size_is_bounded() -> None:
    assert service.MAX_BATCH <= 1000
