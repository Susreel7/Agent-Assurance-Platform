"""Unit tests for accreditation state machine and materiality reactions."""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.accreditation.schemas import ControlAnswerState
from app.domains.accreditation.service import (
    approver_separation_ok,
    classify_control_answer,
    release_reaction_kind,
    transition_allowed,
)
from app.domains.releases.schemas import AccreditationImpact


@dataclass
class Mapping:
    evidence_kind: str
    strength: str


def test_all_legal_hld_transitions() -> None:
    legal = [
        ("draft", "submitted"),
        ("draft", "withdrawn"),
        ("submitted", "approved"),
        ("submitted", "draft"),
        ("submitted", "withdrawn"),
        ("approved", "suspended"),
        ("approved", "expired"),
        ("approved", "withdrawn"),
        ("suspended", "approved"),
        ("suspended", "expired"),
        ("suspended", "withdrawn"),
        ("expired", "withdrawn"),
    ]
    for frm, to in legal:
        assert transition_allowed(frm, to), f"{frm}->{to} should be allowed"


def test_illegal_transitions_rejected() -> None:
    illegal = [
        ("draft", "approved"),
        ("submitted", "suspended"),
        ("approved", "submitted"),
        ("withdrawn", "draft"),
        ("expired", "approved"),
    ]
    for frm, to in illegal:
        assert not transition_allowed(frm, to), f"{frm}->{to} should be blocked"


def test_withdrawn_from_any_non_terminal() -> None:
    for state in ("draft", "submitted", "approved", "suspended", "expired"):
        assert transition_allowed(state, "withdrawn")


def test_self_approval_rejected() -> None:
    assert not approver_separation_ok("person:alice", "person:alice")
    assert approver_separation_ok("person:alice", "person:bob")


def test_release_reaction_all_impacts() -> None:
    assert release_reaction_kind(AccreditationImpact.SUSPENDS) == "suspend_accreditations"
    assert (
        release_reaction_kind(AccreditationImpact.REQUIRES_REVALIDATION) == "schedule_attestation"
    )
    assert release_reaction_kind(AccreditationImpact.NONE) == "advance_baseline"


def test_unanswerable_control_requires_gap_reason() -> None:
    state, gap, _, _ = classify_control_answer("evidence", [], {})
    assert state is ControlAnswerState.UNANSWERABLE
    assert gap is not None
