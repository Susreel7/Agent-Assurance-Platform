"""Typed control-plane boundary for the evaluate workspace service."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PageMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    next_cursor: str | None = None


class PagedResponse[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[T]
    meta: PageMeta = Field(default_factory=lambda: PageMeta(total=0, limit=0))


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_key: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class DatasetOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    dataset_key: str
    display_name: str
    description: str
    tags: list[Any]
    created_at: datetime
    created_by: str


class ExampleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_key: str = Field(min_length=1, max_length=128)
    split_name: str = "default"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any]
    reference_output: dict[str, Any] | None = None
    source_trace_id: str | None = None


class DatasetRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    examples: list[ExampleCreate] = Field(default_factory=list)
    copy_from_revision_id: UUID | None = None


class DatasetRevisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    dataset_id: UUID
    revision_number: int
    manifest_digest: str
    example_count: int
    created_at: datetime
    created_by: str


class ExampleSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    example_key: str
    ordinal: int
    split_name: str
    tags: list[Any]
    metadata: dict[str, Any]
    content_digest: str
    source_trace_id: str | None
    has_encrypted_payload: bool
    has_input_object: bool
    has_reference_object: bool
    created_at: datetime


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = Field(pattern="^(jsonl|csv)$")
    content: str


class ExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str
    content: str


class AttachmentUploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=64)
    mime_type: str = "application/octet-stream"
    content_base64: str


class AttachmentUploadOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_ref_id: UUID
    storage_ref: str
    content_digest: str
    download: dict[str, Any]


class AttachmentDownloadOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_ref_id: UUID
    mime_type: str
    size_bytes: int
    content_digest: str
    content_base64: str


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_revision_id: UUID
    prompt_revision_pins: dict[str, UUID] = Field(default_factory=dict)
    rule_revision_pins: dict[str, UUID] = Field(default_factory=dict)
    skill_revision_pins: dict[str, UUID] = Field(default_factory=dict)
    context_revision_pins: dict[str, UUID] = Field(default_factory=dict)
    evaluator_revision_ids: list[UUID] = Field(default_factory=list)
    model_route_alias: str | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict)


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_key: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    spec: ExperimentSpec
    baseline_experiment_id: UUID | None = None
    seed: int = 0
    repetitions: int = Field(default=1, ge=1, le=100)
    concurrency: int = Field(default=2, ge=1, le=32)
    budget_usd: float | None = Field(default=None, ge=0)


class ExperimentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    experiment_key: str
    display_name: str
    status: str
    dataset_revision_id: UUID
    spec_digest: str
    seed: int
    repetitions: int
    concurrency: int
    progress: dict[str, Any]
    aggregates: dict[str, Any]
    created_at: datetime


class ExperimentResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    example_id: UUID
    repetition_index: int
    status: str
    trace_id: str | None
    scores: dict[str, Any]
    latency_ms: int | None
    cost_usd: float | None


class ExperimentResultsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ExperimentResultOut]
    comparison: dict[str, Any] | None = None


class EvaluatorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluator_key: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    kind: str
    config: dict[str, Any] = Field(default_factory=dict)


class EvaluatorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    evaluator_key: str
    display_name: str
    kind: str
    created_at: datetime | None = None
    created_by: str | None = None


class EvaluatorRevisionSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    evaluator_id: UUID
    evaluator_key: str
    kind: str
    revision_number: int
    config_digest: str
    created_at: datetime
    created_by: str


class EvaluatorRevisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    evaluator_id: UUID
    revision_number: int
    config_digest: str
    created_at: datetime
    created_by: str


class EvaluatorDryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: UUID | None = None
    config: dict[str, Any] | None = None
    kind: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ScoreCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(pattern="^(run|span|trace|session|experiment_result)$")
    target_id: str
    name: str
    value_type: str = Field(pattern="^(numeric|boolean|categorical)$")
    value_numeric: float | None = None
    value_boolean: bool | None = None
    value_categorical: str | None = None
    source: str = Field(pattern="^(human|automated)$")
    evaluator_revision_id: UUID | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoreCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=512)
    corrected: ScoreCreate


class ScoreOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    target_type: str
    target_id: str
    name: str
    value_type: str
    source: str
    created_at: datetime
    created_by: str


class ScoreDetailOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    target_type: str
    target_id: str
    name: str
    value_type: str
    value_numeric: float | None = None
    value_boolean: bool | None = None
    value_categorical: str | None = None
    source: str
    evaluator_revision_id: UUID | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_score_id: UUID | None = None
    created_at: datetime
    created_by: str


class OnlineRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_key: str = Field(min_length=1, max_length=128)
    filter: dict[str, Any] = Field(default_factory=dict)
    sample_rate: float = Field(default=0.01, ge=0, le=1)
    sample_hash_salt: str | None = None
    evaluator_revision_ids: list[UUID] = Field(default_factory=list)
    budget_usd: float | None = Field(default=None, ge=0)
    max_concurrency: int = Field(default=2, ge=1, le=32)
    actions: list[dict[str, Any]] = Field(default_factory=list)


class ObserveWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    organization_id: UUID
    project_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict)


class OnlineRuleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    project_id: UUID
    rule_key: str
    enabled: bool = True
    filter: dict[str, Any] = Field(default_factory=dict)
    sample_rate: float
    evaluator_revision_ids: list[Any] = Field(default_factory=list)
    budget_usd: float | None = None
    max_concurrency: int
    spent_usd: float = 0
    circuit_open_until: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class AlertOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    project_id: UUID
    rule_id: UUID | None = None
    action_type: str
    target: str
    payload_digest: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None = None
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    payload_trace_id: str | None = None


class AnnotationQueueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_key: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    item_filter: dict[str, Any] = Field(default_factory=dict)
    rubric: dict[str, Any] = Field(default_factory=dict)
    reviewers_required: int = Field(default=1, ge=1, le=10)


class AnnotationItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: str = Field(pattern="^(trace|span|session|pairwise)$")
    reference_id: str
    pairwise_reference_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee: str
    expected_version: int = 0
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class SubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee: str
    action: str = Field(pattern="^(submit|skip)$")
    scores: dict[str, Any] = Field(default_factory=dict)
    comments: str = ""
    rubric_version: int = 1


class ExportToDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_key: str


class AnnotationQueueOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    project_id: UUID
    queue_key: str
    display_name: str
    item_filter: dict[str, Any] = Field(default_factory=dict)
    rubric: dict[str, Any] = Field(default_factory=dict)
    reviewers_required: int
    created_at: datetime
    created_by: str


class AnnotationItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    queue_id: UUID
    organization_id: UUID
    project_id: UUID
    item_type: str
    reference_id: str
    pairwise_reference_id: str | None = None
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None


class ReleaseGateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_key: str = Field(min_length=1, max_length=128)
    baseline_experiment_id: UUID | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)


class ReleaseGateEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_experiment_id: UUID


class ReleaseGateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    project_id: UUID
    gate_key: str
    baseline_experiment_id: UUID | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    created_by: str


class ReleaseGateEvaluationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    gate_id: UUID
    organization_id: UUID
    project_id: UUID
    candidate_experiment_id: UUID
    passed: bool
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class IdResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID


class OnlineRuleEventJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID | None = None


class ClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claimed: bool


class ExportToDatasetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: UUID


class ReleaseGateEvaluateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class AnnotationConsensusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submissions: int
    disagreement: bool
    spread: float | None = None
    stddev: float | None = None


class ExperimentAggregatesRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aggregates: dict[str, Any] = Field(default_factory=dict)
    comparison: dict[str, Any] | None = None
