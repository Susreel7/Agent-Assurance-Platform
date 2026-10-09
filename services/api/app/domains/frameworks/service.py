"""Framework business logic — questionnaires, mappings and coverage."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import Framework
from app.domains.frameworks import repository as repo
from app.domains.frameworks.schemas import (
    AnswerMode,
    ControlMappingOut,
    ControlMappingUpsert,
    CoverageByFramework,
    FrameworkControlOut,
    FrameworkDetail,
    FrameworkKind,
    FrameworkSummary,
    ImportResult,
    QuestionnaireImport,
    UnmappedControl,
)


class CoverageRow(Protocol):
    control_id: UUID
    control_ref: str
    title: str
    answer_mode: str
    mapping_count: int


class FrameworkError(Exception):
    """Base for everything this module raises."""


class FrameworkNotFoundError(FrameworkError):
    def __init__(self, framework_id: UUID) -> None:
        super().__init__(f"framework {framework_id} not found or not visible")
        self.framework_id = framework_id


class FrameworkReadOnlyError(FrameworkError):
    def __init__(self, framework_id: UUID) -> None:
        super().__init__(
            f"framework {framework_id} is shipped reference data and cannot be modified"
        )
        self.framework_id = framework_id


class ControlNotFoundError(FrameworkError):
    def __init__(self, control_id: UUID) -> None:
        super().__init__(f"control {control_id} not found")
        self.control_id = control_id


class QuestionnaireImportError(FrameworkError):
    pass


class FrameworkSlugTakenError(FrameworkError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"framework slug {slug!r} is already used")
        self.slug = slug


class FrameworkRow(Protocol):
    """Shape of a ``frameworks`` row. A null ``org_id`` marks reference data we ship."""

    id: UUID
    org_id: UUID | None


class ControlRow(Protocol):
    """Shape of one control offered for import."""

    control_ref: str


def is_shipped_framework(framework: FrameworkRow) -> bool:
    return framework.org_id is None


def validate_questionnaire_controls(
    controls: Iterable[ControlRow],
) -> None:
    """Reject duplicate control_refs within one import batch.

    A spreadsheet with two rows for the same reference would otherwise produce an
    ambiguous pack — reviewers navigate by control_ref, so duplicates are never benign.
    """
    seen: set[str] = set()
    for row in controls:
        if row.control_ref in seen:
            raise QuestionnaireImportError(f"duplicate control_ref {row.control_ref!r} in import")
        seen.add(row.control_ref)


def compute_coverage_from_rows(
    framework_id: UUID, rows: Iterable[CoverageRow]
) -> CoverageByFramework:
    """Pure coverage maths for readiness and framework detail screens."""
    mapped = 0
    unmapped_controls: list[UnmappedControl] = []
    total = 0

    for row in rows:
        total += 1
        mode = AnswerMode(row.answer_mode)
        if mode is AnswerMode.NOT_APPLICABLE:
            continue
        if row.mapping_count > 0:
            mapped += 1
            continue
        if mode is AnswerMode.NARRATIVE:
            continue
        unmapped_controls.append(
            UnmappedControl(
                control_id=row.control_id,
                control_ref=row.control_ref,
                title=row.title,
                answer_mode=mode,
            )
        )

    answerable_total = sum(
        1
        for row in rows
        if AnswerMode(row.answer_mode) not in (AnswerMode.NOT_APPLICABLE, AnswerMode.NARRATIVE)
    )
    unmapped = answerable_total - mapped

    return CoverageByFramework(
        framework_id=framework_id,
        total_controls=total,
        mapped=mapped,
        unmapped=max(unmapped, 0),
        unmapped_controls=unmapped_controls,
    )


def _summary(framework: Framework, control_count: int) -> FrameworkSummary:
    return FrameworkSummary(
        id=framework.id,
        slug=framework.slug,
        name=framework.name,
        kind=FrameworkKind(framework.kind),
        publisher=framework.publisher,
        version=framework.version,
        is_builtin=framework.org_id is None,
        control_count=control_count,
    )


async def list_frameworks(
    session: AsyncSession, org_id: UUID, *, kinds: list[str] | None = None
) -> list[FrameworkSummary]:
    rows = await repo.list_frameworks(session, org_id, kinds=kinds)
    return [_summary(fw, count) for fw, count in rows]


async def get_framework_detail(
    session: AsyncSession, org_id: UUID, framework_id: UUID
) -> FrameworkDetail:
    rows = await repo.list_frameworks(session, org_id)
    match = next(((fw, count) for fw, count in rows if fw.id == framework_id), None)
    if match is None:
        raise FrameworkNotFoundError(framework_id)
    fw, count = match
    base = _summary(fw, count)
    return FrameworkDetail(
        **base.model_dump(),
        typical_sectors=list(fw.typical_sectors or []),
        jurisdictions=list(fw.jurisdictions or []),
        source_url=fw.source_url,
        created_at=fw.created_at,
    )


async def list_framework_controls(
    session: AsyncSession, org_id: UUID, framework_id: UUID
) -> list[FrameworkControlOut]:
    if await repo.get_framework(session, org_id, framework_id) is None:
        raise FrameworkNotFoundError(framework_id)
    controls = await repo.list_controls(session, org_id, framework_id)
    return [FrameworkControlOut.model_validate(c) for c in controls]


async def import_questionnaire(
    session: AsyncSession, org_id: UUID, payload: QuestionnaireImport
) -> ImportResult:
    validate_questionnaire_controls(payload.controls)

    if await repo.get_framework_by_slug(session, org_id, payload.slug):
        raise FrameworkSlugTakenError(payload.slug)

    framework = await repo.insert_framework(
        session,
        org_id,
        {
            "slug": payload.slug,
            "name": payload.name,
            "kind": FrameworkKind.QUESTIONNAIRE.value,
        },
    )

    rows = [
        {
            "control_ref": c.control_ref,
            "title": c.title,
            "requirement": c.requirement,
            "section": c.section,
            "ordinal": idx,
            "answer_mode": c.answer_mode.value,
            "text_status": "reviewed",
        }
        for idx, c in enumerate(payload.controls)
    ]
    inserted = await repo.bulk_insert_controls(session, org_id, framework.id, rows)
    return ImportResult(framework_id=framework.id, controls_imported=len(inserted))


async def map_control(
    session: AsyncSession, org_id: UUID, control_id: UUID, payload: ControlMappingUpsert
) -> ControlMappingOut:
    control = await repo.get_control(session, org_id, control_id)
    if control is None:
        raise ControlNotFoundError(control_id)

    framework = await repo.get_framework(session, org_id, control.framework_id)
    if framework is None:
        raise FrameworkNotFoundError(control.framework_id)

    mapping = await repo.upsert_control_mapping(
        session,
        org_id,
        control_id,
        {
            "evidence_kind": payload.evidence_kind,
            "strength": payload.strength.value,
            "producer": payload.producer,
            "narrative_template": payload.narrative_template,
        },
    )
    return ControlMappingOut.model_validate(mapping)


async def seed_obligation_template_links(session: AsyncSession, org_id: UUID) -> int:
    """Repair global control mappings for gap analysis (0013 initially targeted wrong slugs)."""
    return await repo.bind_obligation_templates(
        session,
        org_id,
        (
            ("soc2-trust", "CC6.1", "TOOL-001-allowlist", "require"),
            ("eu-ai-act", "Article 12", "RES-001-forbid-cross-border", "forbid"),
            ("eu-ai-act", "Article 14", "HITL-001-write-approval", "require"),
        ),
    )


async def compute_coverage(
    session: AsyncSession, org_id: UUID, framework_id: UUID
) -> CoverageByFramework:
    if await repo.get_framework(session, org_id, framework_id) is None:
        raise FrameworkNotFoundError(framework_id)
    rows = await repo.fetch_coverage(session, org_id, framework_id)
    return compute_coverage_from_rows(framework_id, rows)


def assert_framework_mutable(framework: FrameworkRow) -> None:
    """Shipped frameworks are reference data; tenants map evidence to them, not edit them."""
    if is_shipped_framework(framework):
        raise FrameworkReadOnlyError(framework.id)
