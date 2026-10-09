"""Evidence schemas.

The constraint that shapes every model here: evidence carries digests, classifications
and decisions, never prompts, completions or tool arguments (AGENTS.md rule 5). The
field lengths below are not defensive programming — they are the reason a collector is
approvable inside a regulated estate, and ``tests/unit/test_evidence.py`` asserts they
have not been widened.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceKind(StrEnum):
    """Names the *fact being evidenced*, not the mechanism that observed it.

    Mechanism belongs in ``detected_by``: the same fact arriving from a span, a
    Kubernetes scan or a manual upload is one label rather than three.
    """

    MODEL_INVENTORY = "model_inventory"
    TOOL_PERMISSION_INVENTORY = "tool_permission_inventory"
    DATA_CLASS_INVENTORY = "data_class_inventory"
    BOM_COMPLETENESS = "bom_completeness"
    OWNERSHIP_RECORD = "ownership_record"
    RESIDENCY_PROOF = "residency_proof"
    OVERSIGHT_RECORD = "oversight_record"
    CHANGE_HISTORY = "change_history"
    MATERIALITY_VERDICT = "materiality_verdict"
    ADVERSARIAL_PROBE = "adversarial_probe"
    VULNERABILITY_SCAN = "vulnerability_scan"
    SERVICE_LEVEL_ATTAINMENT = "service_level_attainment"
    CHAIN_INTEGRITY = "chain_integrity"
    ACCREDITATION_DECISION = "accreditation_decision"
    ATTESTATION_RUN = "attestation_run"
    POLICY_DECISION = "policy_decision"
    ROUTING_DECISION = "routing_decision"
    FAILOVER_EVENT = "failover_event"
    INCIDENT_RECORD = "incident_record"
    APPROVAL_RECORD = "approval_record"
    PROMPT_INTEGRITY = "prompt_integrity"
    DELEGATION_RECORD = "delegation_record"
    GUARDRAIL_ACTIVATION = "guardrail_activation"
    RETENTION_PROOF = "retention_proof"
    ACCESS_REVIEW = "access_review"


class EvidenceOutcome(StrEnum):
    OBSERVED = "observed"
    ALLOW = "allow"
    DENY = "deny"
    REDACT = "redact"
    REROUTE = "reroute"
    REQUIRE_APPROVAL = "require_approval"
    PASS = "pass"
    FAIL = "fail"
    DEGRADED = "degraded"
    ERROR = "error"


class DetectedBy(StrEnum):
    COLLECTOR = "collector"
    OTEL = "otel"
    K8S = "k8s"
    EGRESS = "egress"
    MCP_SCAN = "mcp_scan"
    DESCRIPTOR = "descriptor"
    PROBE = "probe"
    SCANNER = "scanner"
    MANUAL = "manual"
    COMPUTED = "computed"


# ----------------------------------------------------------------------
# Ingest
# ----------------------------------------------------------------------


class EvidenceRecord(BaseModel):
    """One event offered for ingest.

    Field lengths mirror the CHECK constraints in migration 0003. Validating here as
    well means a caller gets a 422 naming the field rather than a 500 from a constraint
    violation, which matters because the most common cause is a collector trying to
    send something it should not.
    """

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    occurred_at: datetime

    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    engagement_id: UUID | None = None
    customer_id: UUID | None = None

    actor: str = Field(default="service:collector", max_length=256)
    action: str = Field(max_length=128)
    outcome: EvidenceOutcome = EvidenceOutcome.OBSERVED

    subject_ref: str | None = Field(default=None, max_length=512)

    region: str | None = Field(default=None, max_length=64)
    data_classes: list[str] = Field(default_factory=list, max_length=64)
    decision: str | None = Field(default=None, max_length=128)
    reason_code: str | None = Field(default=None, max_length=128)

    detail: dict[str, Any] = Field(default_factory=dict)
    detected_by: DetectedBy = DetectedBy.COLLECTOR

    @field_validator("actor")
    @classmethod
    def _principal_shaped(cls, v: str) -> str:
        if not v.startswith(("person:", "role:", "team:", "service:")):
            raise ValueError(
                "actor must be prefixed person:, role:, team: or service: "
                "so accountability is unambiguous"
            )
        return v

    @field_validator("detail")
    @classmethod
    def _detail_bounded(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Reject anything large enough to be a payload.

        A generous structured extras object is a few hundred bytes. Anything reaching a
        kilobyte of *string* content is a prompt, a completion or a tool argument that
        somebody is trying to smuggle through, and the whole trust story rests on that
        being impossible rather than merely discouraged.
        """
        for key, value in v.items():
            if isinstance(value, str) and len(value) > 512:
                raise ValueError(
                    f"detail[{key!r}] exceeds 512 bytes. Evidence stores digests, "
                    "classifications and decisions, never content — store a digest."
                )
        return v


class EvidenceBatchRequest(BaseModel):
    """Bulk ingest. The collector buffers to local disk during an outage, so a
    reconnect commonly delivers thousands at once."""

    model_config = ConfigDict(extra="forbid")

    events: list[EvidenceRecord] = Field(min_length=1, max_length=5000)


class IngestResult(BaseModel):
    accepted: int
    rejected: int
    # Index into the submitted list, with the reason. Returned rather than raised so a
    # buffered replay is not blocked forever by one malformed row.
    errors: list[dict[str, str]] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------


class EvidenceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    recorded_at: datetime

    kind: EvidenceKind

    agent_id: UUID | None
    agent_version_id: UUID | None
    engagement_id: UUID | None
    customer_id: UUID | None

    actor: str
    action: str
    outcome: EvidenceOutcome

    subject_ref: str | None
    region: str | None
    data_classes: list[str]
    decision: str | None
    reason_code: str | None

    detail: dict[str, Any]
    content_digest: str
    detected_by: str

    batch_id: UUID | None
    leaf_index: int | None

    @property
    def is_anchored(self) -> bool:
        return self.batch_id is not None


class EvidencePage(BaseModel):
    items: list[EvidenceEventOut]
    total: int
    limit: int
    offset: int


class EvidenceBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seq: int
    window_start: datetime
    window_end: datetime
    leaf_count: int
    tree_size: int
    merkle_root: str
    prev_batch_digest: str
    batch_digest: str
    sealed_at: datetime
    sealed_by: str
    signature: str | None
    signing_key_ref: str | None

    @property
    def is_signed(self) -> bool:
        return self.signature is not None


# ----------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------


class BatchVerification(BaseModel):
    """Result of re-deriving one batch from the events it claims to cover."""

    seq: int
    batch_id: UUID
    is_valid: bool

    leaf_count_matches: bool
    root_matches: bool
    chain_link_matches: bool
    signature_valid: bool | None = Field(
        default=None, description="None when the batch carries no signature"
    )

    stored_root: str
    recomputed_root: str
    failure_reason: str | None = None


class ChainVerification(BaseModel):
    """Whole-chain result. This is what the trust portal renders, and what an auditor
    is really asking for when they ask whether the log can be trusted."""

    org_id: UUID
    verified_at: datetime

    is_valid: bool
    batches_checked: int
    first_seq: int | None
    last_seq: int | None
    tree_size: int

    # Populated only for failures, so a healthy chain is a small response.
    broken_at_seq: int | None = None
    failure_reason: str | None = None
    batch_results: list[BatchVerification] = Field(default_factory=list)

    # Events accepted but not yet sealed. Not a fault — the sealer runs on a cadence —
    # but a number that keeps growing means the worker has stopped.
    unsealed_count: int = 0

    def headline(self) -> str:
        if not self.is_valid:
            return (
                f"Chain broken at batch {self.broken_at_seq}: "
                f"{self.failure_reason or 'unknown cause'}"
            )
        if self.batches_checked == 0:
            return "No sealed evidence yet"
        return f"{self.tree_size} events verified across {self.batches_checked} sealed batches"


class InclusionProof(BaseModel):
    """Proof that one event is in a published root.

    The audit path carries sibling *digests*, so handing this to a customer discloses
    nothing about any other event — which is what makes it safe to publish per-event
    proofs to a shared trust portal.
    """

    event_id: UUID
    content_digest: str

    batch_id: UUID
    batch_seq: int
    leaf_index: int
    tree_size: int

    merkle_root: str
    audit_path: list[str]

    is_verified: bool
    algorithm: str = "rfc6962-sha256"


class SealResult(BaseModel):
    batch: EvidenceBatchOut | None
    sealed_count: int
    reason: str | None = Field(
        default=None, description="Why nothing was sealed, when batch is None"
    )
