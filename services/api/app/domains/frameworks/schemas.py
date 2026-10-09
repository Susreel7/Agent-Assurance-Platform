"""Framework schemas — reference controls and the mappings that answer them.

Shipped frameworks (``org_id`` null in the database) are read-only to tenants; only
mappings with a tenant ``org_id`` overlay how this organisation's evidence satisfies a
control. That split is what lets one evidence pipeline serve forty questionnaire formats.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FrameworkKind(StrEnum):
    STANDARD = "standard"
    REGULATION = "regulation"
    CERTIFICATION = "certification"
    QUESTIONNAIRE = "questionnaire"
    INTERNAL_POLICY = "internal_policy"


class AnswerMode(StrEnum):
    EVIDENCE = "evidence"
    NARRATIVE = "narrative"
    HYBRID = "hybrid"
    NOT_APPLICABLE = "not_applicable"


class MappingStrength(StrEnum):
    SATISFIES = "satisfies"
    PARTIALLY_SATISFIES = "partially_satisfies"
    SUPPORTS = "supports"


class FrameworkSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    kind: FrameworkKind
    publisher: str | None
    version: str | None
    is_builtin: bool = Field(description="True when we shipped it (org_id IS NULL)")
    control_count: int


class FrameworkDetail(FrameworkSummary):
    typical_sectors: list[str] = Field(default_factory=list)
    jurisdictions: list[str] = Field(default_factory=list)
    source_url: str | None = None
    created_at: datetime


class FrameworkControlOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    framework_id: UUID
    control_ref: str
    title: str
    requirement: str | None
    section: str | None
    ordinal: int
    answer_mode: AnswerMode


class ControlMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    control_id: UUID
    evidence_kind: str
    strength: MappingStrength
    producer: str
    narrative_template: str | None
    created_at: datetime


class ControlMappingUpsert(BaseModel):
    evidence_kind: str = Field(min_length=1, max_length=64)
    strength: MappingStrength = MappingStrength.SATISFIES
    producer: str = Field(min_length=1, max_length=128)
    narrative_template: str | None = Field(default=None, max_length=2000)


class QuestionnaireControlRow(BaseModel):
    control_ref: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    requirement: str | None = Field(default=None, max_length=4000)
    section: str | None = Field(default=None, max_length=128)
    answer_mode: AnswerMode = AnswerMode.EVIDENCE


class QuestionnaireImport(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    name: str = Field(min_length=1, max_length=256)
    controls: list[QuestionnaireControlRow] = Field(min_length=1)


class ImportResult(BaseModel):
    framework_id: UUID
    controls_imported: int


class UnmappedControl(BaseModel):
    control_id: UUID
    control_ref: str
    title: str
    answer_mode: AnswerMode


class CoverageByFramework(BaseModel):
    framework_id: UUID
    total_controls: int
    mapped: int
    unmapped: int
    unmapped_controls: list[UnmappedControl] = Field(default_factory=list)
