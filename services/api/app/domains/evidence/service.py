"""Evidence business logic: ingest, sealing, verification, inclusion proofs.

**The canonical leaf encoding in ``canonical_leaf`` is frozen** (AGENTS.md rule 10).
Every sealed batch in every install depends on it. A change to the field order, the
separator, the null placeholder or the timestamp format silently invalidates every chain
ever written, and the failure surfaces as "your audit log has been tampered with" at a
customer site. If the encoding must change, it becomes ``aap.evidence.v2`` alongside v1,
with the version recorded per event — never an edit to what is below.

Sealing is a batch operation for a reason worth restating: a chain where each row hashes
the previous row serialises every insert behind one lock. That caps ingest at a few
hundred events per second per organisation regardless of hardware, and evidence ingest is
the one path that must never push back on the collector — a gap in an audit trail
outlives whatever caused it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.evidence import merkle
from app.domains.evidence import repository as repo
from app.domains.evidence.schemas import (
    BatchVerification,
    ChainVerification,
    EvidenceBatchOut,
    EvidenceEventOut,
    EvidenceRecord,
    InclusionProof,
    IngestResult,
    SealResult,
)
from app.providers.signing import build_signer

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Frozen constants — see the module docstring before touching any of these
# ----------------------------------------------------------------------

LEAF_SCHEME = "aap.evidence.v1"
BATCH_SCHEME = "aap.batch.v1"

#: Predecessor digest for the first batch in an organisation's chain. A fixed,
#: publishable value, so an auditor can confirm they are looking at the true start of
#: the log rather than at a chain that had earlier batches removed.
GENESIS_DIGEST = merkle.format_hash(hashlib.sha256(b"aap.genesis.v1").digest())

#: Placeholder for an absent optional field. A literal that cannot occur in any real
#: value, so an absent region and a region named "-" cannot collide.
NULL_FIELD = "\x00"

#: Field separator. Also cannot occur in any real value.
SEPARATOR = "\x1e"


class EvidenceError(Exception):
    """Base for evidence domain failures."""


class BatchNotFoundError(EvidenceError):
    pass


class EventNotFoundError(EvidenceError):
    pass


class EventNotAnchoredError(EvidenceError):
    """An inclusion proof was requested for an event the sealer has not reached."""


# ----------------------------------------------------------------------
# Canonicalisation — FROZEN
# ----------------------------------------------------------------------


def _field(value: Any) -> str:
    if value is None:
        return NULL_FIELD
    if isinstance(value, datetime):
        # Always UTC, always microseconds. A naive datetime is a bug upstream; treating
        # it as UTC here rather than raising would produce a digest that cannot be
        # reproduced from the stored row.
        if value.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        # Sorted, so two collectors reporting the same classes in different orders
        # produce the same digest.
        return ",".join(sorted(str(v) for v in value))
    return str(value)


def _canonical_detail(detail: dict[str, Any]) -> str:
    """Detail rendered deterministically.

    ``sort_keys`` with the tightest separators, so an equivalent object always yields
    identical bytes regardless of how the caller happened to build it.
    """
    return json.dumps(detail, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_leaf(
    org_id: UUID,
    record: EvidenceRecord,
) -> bytes:
    """The exact bytes hashed to produce ``content_digest``.

    FROZEN. Field order below is the contract. Read the module docstring.
    """
    fields = [
        LEAF_SCHEME,
        _field(org_id),
        _field(record.kind),
        _field(record.occurred_at),
        _field(record.agent_id),
        _field(record.agent_version_id),
        _field(record.engagement_id),
        _field(record.customer_id),
        _field(record.actor),
        _field(record.action),
        _field(record.outcome),
        _field(record.subject_ref),
        _field(record.region),
        _field(record.data_classes),
        _field(record.decision),
        _field(record.reason_code),
        _canonical_detail(record.detail),
    ]
    return SEPARATOR.join(fields).encode("utf-8")


def content_digest(org_id: UUID, record: EvidenceRecord) -> str:
    return merkle.format_hash(hashlib.sha256(canonical_leaf(org_id, record)).digest())


def batch_digest(
    org_id: UUID,
    seq: int,
    window_start: datetime,
    window_end: datetime,
    leaf_count: int,
    tree_size: int,
    merkle_root: str,
    prev_batch_digest: str,
) -> str:
    """The chain link. FROZEN, for the same reason as ``canonical_leaf``.

    ``tree_size`` is inside the digest deliberately: without it, a batch could be
    replaced by a different batch of the same leaf count at the same sequence number
    and the link would still verify.
    """
    fields = [
        BATCH_SCHEME,
        _field(org_id),
        str(seq),
        _field(window_start),
        _field(window_end),
        str(leaf_count),
        str(tree_size),
        merkle_root,
        prev_batch_digest,
    ]
    payload = SEPARATOR.join(fields).encode("utf-8")
    return merkle.format_hash(hashlib.sha256(payload).digest())


# ----------------------------------------------------------------------
# Ingest
# ----------------------------------------------------------------------


async def record_events(
    session: AsyncSession,
    org_id: UUID,
    records: list[EvidenceRecord],
) -> IngestResult:
    """Accept events, computing each digest on arrival.

    Malformed rows are reported by index rather than raised. A collector replaying a
    disk buffer must not be blocked forever by one bad row, and dropping the whole
    batch to reject a single event loses more evidence than it protects.
    """
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for index, record in enumerate(records):
        try:
            digest = content_digest(org_id, record)
        except ValueError as exc:
            errors.append({"index": str(index), "error": str(exc)})
            continue

        rows.append(
            {
                "occurred_at": record.occurred_at,
                "kind": record.kind.value,
                "agent_id": record.agent_id,
                "agent_version_id": record.agent_version_id,
                "engagement_id": record.engagement_id,
                "customer_id": record.customer_id,
                "actor": record.actor,
                "action": record.action,
                "outcome": record.outcome.value,
                "subject_ref": record.subject_ref,
                "region": record.region,
                "data_classes": record.data_classes,
                "decision": record.decision,
                "reason_code": record.reason_code,
                "detail": record.detail,
                "content_digest": digest,
                "detected_by": record.detected_by.value,
            }
        )

    inserted = await repo.insert_events(session, org_id, rows)

    return IngestResult(accepted=len(inserted), rejected=len(errors), errors=errors)


async def record_one(
    session: AsyncSession,
    org_id: UUID,
    record: EvidenceRecord,
) -> UUID:
    """Single-event ingest, for the many internal callers that emit one fact.

    Every domain that makes a governed decision routes through here rather than writing
    to the table, which is what keeps the digest computation in one place.
    """
    result = await repo.insert_events(
        session,
        org_id,
        [
            {
                "occurred_at": record.occurred_at,
                "kind": record.kind.value,
                "agent_id": record.agent_id,
                "agent_version_id": record.agent_version_id,
                "engagement_id": record.engagement_id,
                "customer_id": record.customer_id,
                "actor": record.actor,
                "action": record.action,
                "outcome": record.outcome.value,
                "subject_ref": record.subject_ref,
                "region": record.region,
                "data_classes": record.data_classes,
                "decision": record.decision,
                "reason_code": record.reason_code,
                "detail": record.detail,
                "content_digest": content_digest(org_id, record),
                "detected_by": record.detected_by.value,
            }
        ],
    )
    if not result:
        raise EvidenceError("evidence insert returned no id")
    return result[0]


# ----------------------------------------------------------------------
# Sealing
# ----------------------------------------------------------------------

#: Events newer than this are left for the next cycle. A collector buffering through a
#: network outage delivers late, and sealing a window before its stragglers arrive
#: would leave them permanently unanchorable — the batch covering their window is
#: already closed.
SEAL_LAG = timedelta(minutes=5)

#: Ceiling on one batch. Large enough that sealing is infrequent, small enough that an
#: inclusion proof stays short: the audit path is log2 of this.
MAX_BATCH_LEAVES = 10_000


async def seal_pending(
    session: AsyncSession,
    org_id: UUID,
    *,
    now: datetime | None = None,
    sealed_by: str = "service:worker",
) -> SealResult:
    """Group unanchored events into a batch, build its Merkle root, chain it and sign it.

    Runs inside one transaction. If any part fails the whole batch is abandoned and the
    events stay unanchored for the next cycle, which is the correct failure mode: an
    unanchored event is still evidence, whereas a batch whose root does not match its
    leaves is worse than no batch at all.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - SEAL_LAG

    pending = await repo.fetch_unsealed(session, org_id, until=cutoff, limit=MAX_BATCH_LEAVES)
    if not pending:
        return SealResult(batch=None, sealed_count=0, reason="no events awaiting a seal")

    # get_last_batch takes a row lock, so two sealers cannot both claim this sequence.
    previous = await repo.get_last_batch(session, org_id)
    seq = 0 if previous is None else previous.seq + 1
    prev_digest = GENESIS_DIGEST if previous is None else previous.batch_digest
    prior_size = 0 if previous is None else previous.tree_size

    digests = [e.content_digest for e in pending]
    root = merkle.format_hash(merkle.root_from_digests(digests))

    window_start = pending[0].occurred_at
    # Exclusive upper bound, and strictly greater than window_start so the
    # evidence_batches_window_sane constraint holds for a batch whose events all share
    # a single timestamp.
    one_tick = timedelta(microseconds=1)
    window_end = max(pending[-1].occurred_at + one_tick, window_start + one_tick)

    tree_size = prior_size + len(pending)
    digest = batch_digest(
        org_id=org_id,
        seq=seq,
        window_start=window_start,
        window_end=window_end,
        leaf_count=len(pending),
        tree_size=tree_size,
        merkle_root=root,
        prev_batch_digest=prev_digest,
    )

    signature: str | None = None
    key_ref: str | None = None
    try:
        signer = build_signer()
        signature = signer.sign(digest.encode("ascii"))
        key_ref = signer.key_id
    except Exception:
        # An unsigned batch is still verifiable, just not attributable. Refusing to
        # seal because a KMS is briefly unreachable would stop the chain advancing,
        # which is the larger harm.
        log.warning("batch %s sealed without a signature", seq, exc_info=True)

    batch = await repo.insert_batch(
        session,
        org_id,
        {
            "seq": seq,
            "window_start": window_start,
            "window_end": window_end,
            "leaf_count": len(pending),
            "tree_size": tree_size,
            "merkle_root": root,
            "prev_batch_digest": prev_digest,
            "batch_digest": digest,
            "sealed_by": sealed_by,
            "signature": signature,
            "signing_key_ref": key_ref,
        },
    )

    anchored = await repo.anchor_events(
        session,
        org_id,
        batch.id,
        [(e.id, e.occurred_at, i) for i, e in enumerate(pending)],
    )
    if anchored != len(pending):
        # Another sealer anchored some of these between the read and the update. The
        # root we just committed to does not describe this batch, so abandon it.
        raise EvidenceError(f"anchored {anchored} of {len(pending)} events; batch {seq} abandoned")

    return SealResult(batch=EvidenceBatchOut.model_validate(batch), sealed_count=len(pending))


# ----------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------


async def verify_batch(
    session: AsyncSession,
    org_id: UUID,
    batch_id: UUID,
    *,
    expected_prev_digest: str | None = None,
) -> BatchVerification:
    """Re-derive one batch from the events it claims to cover."""
    batch = await repo.get_batch(session, org_id, batch_id)
    if batch is None:
        raise BatchNotFoundError(f"batch {batch_id} not found")

    leaves = await repo.fetch_batch_leaves(session, org_id, batch_id)
    recomputed = merkle.format_hash(merkle.root_from_digests([d for _, _, d in leaves]))

    leaf_count_matches = len(leaves) == batch.leaf_count
    root_matches = recomputed == batch.merkle_root
    chain_link_matches = (
        expected_prev_digest is None or batch.prev_batch_digest == expected_prev_digest
    )

    signature_valid: bool | None = None
    if batch.signature is not None:
        try:
            signature_valid = build_signer().verify(
                batch.batch_digest.encode("ascii"), batch.signature
            )
        except Exception:
            log.warning("signature check failed for batch %s", batch.seq, exc_info=True)
            signature_valid = False

    reasons: list[str] = []
    if not leaf_count_matches:
        reasons.append(
            f"batch claims {batch.leaf_count} leaves but {len(leaves)} events carry its id"
        )
    if not root_matches:
        reasons.append("recomputed Merkle root does not match the sealed root")
    if not chain_link_matches:
        reasons.append("prev_batch_digest does not match the preceding batch")
    if signature_valid is False:
        reasons.append("signature does not verify against the configured key")

    return BatchVerification(
        seq=batch.seq,
        batch_id=batch.id,
        is_valid=not reasons,
        leaf_count_matches=leaf_count_matches,
        root_matches=root_matches,
        chain_link_matches=chain_link_matches,
        signature_valid=signature_valid,
        stored_root=batch.merkle_root,
        recomputed_root=recomputed,
        failure_reason="; ".join(reasons) or None,
    )


async def verify_chain(
    session: AsyncSession,
    org_id: UUID,
    *,
    from_seq: int | None = None,
    max_batches: int = 500,
) -> ChainVerification:
    """Walk the chain forward, re-deriving every root and every link.

    Stops at the first break. Continuing past one would produce a long list of failures
    that all describe the same event, and the first break is the only one that tells an
    operator where to look.
    """
    batches = await repo.list_batches(
        session, org_id, from_seq=from_seq, limit=max_batches, ascending=True
    )
    unsealed = await repo.update_events_anchored_stat(session, org_id)

    if not batches:
        return ChainVerification(
            org_id=org_id,
            verified_at=datetime.now(UTC),
            is_valid=True,
            batches_checked=0,
            first_seq=None,
            last_seq=None,
            tree_size=0,
            unsealed_count=unsealed,
        )

    results: list[BatchVerification] = []
    # When starting mid-chain the caller has not given us the preceding digest, so the
    # first link is unverifiable rather than wrong.
    expected_prev = GENESIS_DIGEST if batches[0].seq == 0 else None
    expected_size = 0 if batches[0].seq == 0 else None

    broken_seq: int | None = None
    failure: str | None = None

    for batch in batches:
        result = await verify_batch(session, org_id, batch.id, expected_prev_digest=expected_prev)

        # tree_size must grow by exactly the leaf count, or a batch has been removed.
        if expected_size is not None and batch.tree_size != expected_size + batch.leaf_count:
            result = result.model_copy(
                update={
                    "is_valid": False,
                    "failure_reason": (
                        f"tree_size jumped from {expected_size} to {batch.tree_size} "
                        f"for {batch.leaf_count} leaves, which means a batch is missing"
                    ),
                }
            )

        results.append(result)

        if not result.is_valid:
            broken_seq = batch.seq
            failure = result.failure_reason
            break

        expected_prev = batch.batch_digest
        expected_size = batch.tree_size

    last = results[-1]
    checked = list(batches[: len(results)])

    return ChainVerification(
        org_id=org_id,
        verified_at=datetime.now(UTC),
        is_valid=broken_seq is None,
        batches_checked=len(results),
        first_seq=checked[0].seq,
        last_seq=checked[-1].seq,
        tree_size=checked[-1].tree_size,
        broken_at_seq=broken_seq,
        failure_reason=failure,
        # Only failures are returned in full: a healthy chain of 500 batches would
        # otherwise produce a response nobody reads.
        batch_results=[r for r in results if not r.is_valid] or [last],
        unsealed_count=unsealed,
    )


async def build_inclusion_proof(
    session: AsyncSession,
    org_id: UUID,
    event_id: UUID,
    *,
    occurred_at: datetime | None = None,
) -> InclusionProof:
    """Prove one event is in its batch's published root.

    The audit path carries sibling digests only, which is what makes it safe to hand a
    customer a proof about their own event on a shared trust portal.
    """
    event = await repo.get_event(session, org_id, event_id, occurred_at)
    if event is None:
        raise EventNotFoundError(f"evidence event {event_id} not found")
    if event.batch_id is None or event.leaf_index is None:
        raise EventNotAnchoredError(
            f"event {event_id} is accepted but not yet sealed, so no proof exists yet"
        )

    batch = await repo.get_batch(session, org_id, event.batch_id)
    if batch is None:
        raise BatchNotFoundError(f"batch {event.batch_id} not found")

    leaves = await repo.fetch_batch_leaves(session, org_id, event.batch_id)
    leaf_hashes = [merkle.leaf_hash(d) for _, _, d in leaves]

    path = merkle.inclusion_proof(leaf_hashes, event.leaf_index)
    verified = merkle.verify_inclusion(
        leaf=merkle.leaf_hash(event.content_digest),
        index=event.leaf_index,
        tree_size=len(leaf_hashes),
        path=path,
        expected_root=merkle.parse_hash(batch.merkle_root),
    )

    return InclusionProof(
        event_id=event.id,
        content_digest=event.content_digest,
        batch_id=batch.id,
        batch_seq=batch.seq,
        leaf_index=event.leaf_index,
        tree_size=len(leaf_hashes),
        merkle_root=batch.merkle_root,
        audit_path=[merkle.format_hash(h) for h in path],
        is_verified=verified,
    )


# ----------------------------------------------------------------------
# Checkpoints
# ----------------------------------------------------------------------


async def publish_checkpoint(
    session: AsyncSession,
    org_id: UUID,
    *,
    published_to: str,
    external_ref: str | None = None,
) -> dict[str, Any]:
    """Publish the current chain head to a named audience.

    Once a customer or auditor holds a checkpoint, history before it cannot be rewritten
    even with full database access. That property is the whole reason the log is worth
    trusting rather than merely worth reading, so publishing is a deliberate act with a
    named recipient rather than a background side effect.
    """
    head = await repo.get_last_batch(session, org_id)
    if head is None:
        raise EvidenceError("nothing to publish: no batch has been sealed yet")

    signature: str | None = None
    try:
        signature = build_signer().sign(
            f"{head.tree_size}{SEPARATOR}{head.merkle_root}".encode("ascii")
        )
    except Exception:
        log.warning("checkpoint published without a signature", exc_info=True)

    checkpoint = await repo.insert_checkpoint(
        session,
        org_id,
        {
            "batch_id": head.id,
            "tree_size": head.tree_size,
            "root": head.merkle_root,
            "published_to": published_to,
            "external_ref": external_ref,
            "signature": signature,
        },
    )

    return {
        "id": checkpoint.id,
        "tree_size": checkpoint.tree_size,
        "root": checkpoint.root,
        "published_to": checkpoint.published_to,
        "published_at": checkpoint.published_at,
        "signature": checkpoint.signature,
    }


# ----------------------------------------------------------------------
# Reads
# ----------------------------------------------------------------------


async def list_events(
    session: AsyncSession,
    org_id: UUID,
    **filters: Any,
) -> tuple[list[EvidenceEventOut], int]:
    limit = int(filters.pop("limit", 100))
    offset = int(filters.pop("offset", 0))

    rows = await repo.list_events(session, org_id, limit=limit, offset=offset, **filters)
    total = await repo.count_events(session, org_id, **filters)

    return [EvidenceEventOut.model_validate(r) for r in rows], total


async def list_batches(
    session: AsyncSession, org_id: UUID, *, limit: int = 50, offset: int = 0
) -> tuple[list[EvidenceBatchOut], int]:
    rows = await repo.list_batches(session, org_id, limit=limit, offset=offset)
    total = await repo.count_batches(session, org_id)
    return [EvidenceBatchOut.model_validate(r) for r in rows], total


async def kind_counts(
    session: AsyncSession, org_id: UUID, *, since: datetime | None = None
) -> dict[str, int]:
    return await repo.fetch_kind_counts(session, org_id, since=since)


async def list_checkpoints(
    session: AsyncSession, org_id: UUID, *, published_to: str | None = None
) -> list[dict[str, Any]]:
    rows = await repo.list_checkpoints(session, org_id, published_to=published_to)
    return [
        {
            "id": r.id,
            "tree_size": r.tree_size,
            "root": r.root,
            "published_to": r.published_to,
            "published_at": r.published_at,
            "signature": r.signature,
        }
        for r in rows
    ]


async def retention_horizon() -> datetime:
    """Oldest date evidence is kept for. Read from configuration so a BYOC customer
    can set it to their own retention policy rather than to ours."""
    days = get_settings().evidence_retention_days
    return datetime.now(UTC) - timedelta(days=days)
