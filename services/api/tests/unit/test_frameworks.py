"""Unit tests for the frameworks domain — pure validation and coverage maths."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.domains.frameworks.schemas import QuestionnaireControlRow, QuestionnaireImport
from app.domains.frameworks.service import (
    FrameworkReadOnlyError,
    QuestionnaireImportError,
    assert_framework_mutable,
    compute_coverage_from_rows,
    is_shipped_framework,
    validate_questionnaire_controls,
)

FW = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@dataclass
class CoverageRow:
    control_id: UUID
    control_ref: str
    title: str
    answer_mode: str
    mapping_count: int


class ShippedFramework:
    id = FW
    org_id = None


class TenantFramework:
    id = FW
    org_id = uuid4()


def test_duplicate_control_ref_rejected() -> None:
    payload = QuestionnaireImport(
        slug="acme-q",
        name="Acme questionnaire",
        controls=[
            QuestionnaireControlRow(control_ref="Q-1", title="One"),
            QuestionnaireControlRow(control_ref="Q-1", title="Duplicate"),
        ],
    )
    with pytest.raises(QuestionnaireImportError, match="duplicate"):
        validate_questionnaire_controls(payload.controls)


def test_coverage_counts_mapped_and_unmapped() -> None:
    c1, c2 = uuid4(), uuid4()
    result = compute_coverage_from_rows(
        FW,
        [
            CoverageRow(c1, "A.1", "Mapped", "evidence", 2),
            CoverageRow(c2, "A.2", "Gap", "evidence", 0),
        ],
    )
    assert result.total_controls == 2
    assert result.mapped == 1
    assert result.unmapped == 1
    assert len(result.unmapped_controls) == 1
    assert result.unmapped_controls[0].control_ref == "A.2"


def test_narrative_controls_do_not_count_as_unmapped_gaps() -> None:
    result = compute_coverage_from_rows(
        FW,
        [CoverageRow(uuid4(), "N.1", "Statement", "narrative", 0)],
    )
    assert result.unmapped == 0
    assert result.unmapped_controls == []


def test_shipped_framework_is_read_only() -> None:
    assert is_shipped_framework(ShippedFramework())
    assert not is_shipped_framework(TenantFramework())
    with pytest.raises(FrameworkReadOnlyError):
        assert_framework_mutable(ShippedFramework())
