"""Score recording and correction audit."""

from __future__ import annotations

from uuid import UUID

from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.scores.schemas import ScoreCreate
from evaluate.errors import NotFoundError, ValidationError


def create_score(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    payload: ScoreCreate,
    actor: str,
) -> UUID:
    if payload.value_type == "numeric" and payload.value_numeric is None:
        raise ValidationError("value_numeric required for numeric scores")
    if payload.value_type == "boolean" and payload.value_boolean is None:
        raise ValidationError("value_boolean required for boolean scores")
    if payload.value_type == "categorical" and not payload.value_categorical:
        raise ValidationError("value_categorical required for categorical scores")
    return repo.insert_score(
        conn,
        org_id=org_id,
        project_id=project_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        name=payload.name,
        value_type=payload.value_type,
        value_numeric=payload.value_numeric,
        value_boolean=payload.value_boolean,
        value_categorical=payload.value_categorical,
        source=payload.source,
        evaluator_revision_id=payload.evaluator_revision_id,
        explanation=payload.explanation,
        metadata=payload.metadata,
        supersedes_score_id=None,
        actor=actor,
    )


def correct_score(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    original_score_id: UUID,
    payload: ScoreCreate,
    reason: str,
    actor: str,
) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM evaluate.scores
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (original_score_id, org_id, project_id),
        )
        if not cur.fetchone():
            raise NotFoundError("original score not found")
    corrected_id = repo.insert_score(
        conn,
        org_id=org_id,
        project_id=project_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        name=payload.name,
        value_type=payload.value_type,
        value_numeric=payload.value_numeric,
        value_boolean=payload.value_boolean,
        value_categorical=payload.value_categorical,
        source="human",
        evaluator_revision_id=payload.evaluator_revision_id,
        explanation=payload.explanation,
        metadata=payload.metadata,
        supersedes_score_id=original_score_id,
        actor=actor,
    )
    repo.record_score_correction(
        conn,
        org_id=org_id,
        project_id=project_id,
        original_score_id=original_score_id,
        corrected_score_id=corrected_id,
        reason=reason,
        actor=actor,
    )
    return corrected_id
