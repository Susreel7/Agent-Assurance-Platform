"""``aap.action.v1`` — the canonical action envelope, typed.

One envelope for every capability kind (`design/15` §9), so an MCP tool call, a shell
command and an outbound HTTP request arrive in one shape and become one row in
``agent_actions``. The wire format is nested because that is what a collector serialises;
migration `0024` flattens it, and the two vocabularies are kept in step by
``tests/unit/test_agent_actions.py``, which is the only place that can see both.

There is no ingest endpoint in this slice. The envelope lands first so that the collector
and the table are written against one definition rather than two that drift — the failure
this codebase has already had once, in D-057, where four of seven audit categories failed
at INSERT while the trail looked healthy.

**Every model here sets ``extra="forbid"``, and that is the privacy control.** A collector
that sends ``prompt``, ``completion``, ``stdout``, ``payload``, ``file_contents`` or a raw
argv array gets a 422 naming the field. Silently dropping unknown keys would be safe for
storage and useless as an answer to "prove you don't store our code", because nobody can
see a field that was quietly discarded. Forward compatibility is handled by the ``v1`` in
the schema identifier: a collector with new fields sends a new schema version, and the
ingest path refuses one it does not know rather than half-reading it.

Two fields in `design/15` §9 are deliberately absent, matching `0024`:

``arguments.payload_ref``
    The MVP has no audited-reveal path for a pointer to resolve through, and a pointer
    with no resolver is an invitation to build one.

``provenance.signature``
    Collector signing keys are V1. ``prev_event_hash`` plus ``event_hash`` already make
    suppression detectable (threat model AP-9), which is the property the MVP needs.

Both are rejected rather than ignored, by the same ``extra="forbid"``.

There is also no ``received_at``. A sender cannot know when the receiver received it, and
the pair ``(occurred_at, received_at)`` is the clock-skew and suppression-delay forensics
only if the second half is stamped by us. Same reasoning as ``AuditRecord`` in
``security_audit``, which likewise refuses a caller-supplied ``occurred_at``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.domains.registry.schemas import LifecycleState

SchemaId = Literal["aap.action.v1"]

SCHEMA_ID: Final[SchemaId] = "aap.action.v1"

MAX_DELEGATION_DEPTH = 8


# ---------------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------------
# The column type is ``bytea``; the wire type is text. `design/15` writes digests as
# ``sha256:<hex>`` while `0017`'s audit trail and `0018`'s connections use bare hex. Both
# are accepted and normalised to bare lowercase hex here, so a collector written against
# either half of the design documents works and the repository has exactly one form to
# convert. Rejecting one spelling would be a compatibility break over punctuation.

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256_hex(value: str) -> str:
    text = value.strip().lower().removeprefix("sha256:")
    if not _SHA256_RE.match(text):
        raise ValueError(
            "expected a sha256 digest: 64 hex characters, optionally 'sha256:' prefixed"
        )
    return text


Sha256Hex = Annotated[str, AfterValidator(_sha256_hex)]


def digest_bytes(value: str | None) -> bytes | None:
    """Wire form to column form. The one place hex becomes ``bytea``."""
    return None if value is None else bytes.fromhex(value)


def _aware(value: datetime) -> datetime:
    """Refuse a naive timestamp.

    The column is ``timestamptz`` and the partition a row lands in is decided by
    ``occurred_at``. A naive datetime would be interpreted against the server's zone,
    which silently moves an action between months for anybody not in UTC.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must carry a UTC offset (RFC 3339)")
    return value


Rfc3339 = Annotated[datetime, AfterValidator(_aware)]


# ---------------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------------
# Each of these mirrors a CHECK constraint in `0024`. They are duplicated rather than
# generated because a CHECK is not introspectable as a list without parsing it, and a
# generated vocabulary would hide a widening that only happened on one side.
# ``tests/unit/test_agent_actions.py`` reads both and asserts they agree, which is the
# cheap version of the same guarantee.


class CapabilityKind(StrEnum):
    """`design/15` §3, in full, including the rows we cannot govern.

    ``BROWSER_ACT`` is listed although it is permanently grade E: an honest gap beats a
    silent one (Q-J). ``UNKNOWN`` exists because a collector that sees a capability it
    cannot classify must still report it — a discovery that never lands is the one thing
    worse than a vague one.
    """

    MODEL_INVOKE = "model.invoke"
    MCP_TOOL = "mcp.tool"
    SHELL_EXEC = "shell.exec"
    NET_HTTP = "net.http"
    FS_READ = "fs.read"
    FS_WRITE = "fs.write"
    VCS_WRITE = "vcs.write"
    DB_QUERY = "db.query"
    CLOUD_API = "cloud.api"
    AGENT_DELEGATE = "agent.delegate"
    MEMORY_WRITE = "memory.write"
    RETRIEVAL_QUERY = "retrieval.query"
    PACKAGE_PUBLISH = "package.publish"
    BROWSER_ACT = "browser.act"
    UNKNOWN = "unknown"


class ActionOutcome(StrEnum):
    """`design/14` §6.2, plus ``OBSERVED``.

    ``OBSERVED`` is the MVP's own outcome. The ledger is read-only, so most rows record
    an action that happened with no decision taken. Folding it into ``ALLOW`` would claim
    a permission decision we never made, and every coverage number computed from this
    column would be a lie in our own favour.
    """

    OBSERVED = "observed"
    ALLOW = "allow"
    ANNOTATE = "annotate"
    MASK = "mask"
    TOKENIZE = "tokenize"
    ROUTE_INTERNAL = "route_internal"
    REQUIRE_APPROVAL = "require_approval"
    STEP_UP_AUTH = "step_up_auth"
    RATE_LIMIT = "rate_limit"
    QUARANTINE = "quarantine"
    DENY = "deny"
    ERROR = "error"


#: Outcomes that assert the platform or a vendor control actually intervened. An
#: intervention at grade E is a contradiction; see ``ActionEnvelope`` below.
ENFORCING_OUTCOMES: frozenset[ActionOutcome] = frozenset(
    {
        ActionOutcome.DENY,
        ActionOutcome.QUARANTINE,
        ActionOutcome.MASK,
        ActionOutcome.TOKENIZE,
        ActionOutcome.ROUTE_INTERNAL,
        ActionOutcome.RATE_LIMIT,
    }
)


class EnforcementGrade(StrEnum):
    """`design/12`. A decision without a grade is a suggestion.

    **A** mediated, **B** interposed with a real veto, **C** vendor-enforced and attested,
    **D** observed afterwards, **E** not covered. ``UNKNOWN`` is accepted at ingestion —
    a collector may know what happened before it knows what it could have done about it —
    and reads as ``E`` everywhere. Use :func:`effective_enforcement_grade`, never a direct
    comparison, or the ungraded population quietly counts as protected.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    UNKNOWN = "unknown"


def effective_enforcement_grade(grade: EnforcementGrade | str | None) -> EnforcementGrade:
    """``unknown`` reads as ``E``. The Python twin of SQL ``effective_enforcement_grade``."""
    if grade is None or grade == EnforcementGrade.UNKNOWN:
        return EnforcementGrade.E
    return EnforcementGrade(grade)


class RootHumanBasis(StrEnum):
    """`design/14` §1. How the chain reaches a person, and the distinction matters.

    A schedule-triggered agent is rooted at whoever approved it, and the evidence should
    say ``APPROVED_BY`` rather than implying they were at the keyboard.
    """

    REGISTERED_BY = "registered_by"
    APPROVED_BY = "approved_by"
    TRIGGERED_BY = "triggered_by"


class ResourceKind(StrEnum):
    HOST = "host"
    PATH = "path"
    REPO = "repo"
    DATABASE = "database"
    CLOUD_RESOURCE = "cloud_resource"
    MODEL = "model"
    MCP_SERVER = "mcp_server"
    PACKAGE = "package"
    INDEX = "index"
    MEMORY_STORE = "memory_store"
    AGENT = "agent"
    UNKNOWN = "unknown"


class ResourceClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class DestinationClass(StrEnum):
    NONE = "none"
    LOOPBACK = "loopback"
    INTERNAL = "internal"
    EXTERNAL_ALLOWLISTED = "external_allowlisted"
    EXTERNAL_UNKNOWN = "external_unknown"


class DataClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    PII = "pii"
    PHI = "phi"
    PCI = "pci"
    SECRET = "secret"
    SOURCE_CODE = "source_code"
    UNKNOWN = "unknown"


class RiskClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class RiskSignal(StrEnum):
    """Categorical, per `design/14` §8.

    There is no risk *score* in this envelope and its absence is the design: a score that
    gates an action is the control nobody can explain to an auditor. Scoring orders a
    review queue and lives outside the ledger.
    """

    SESSION_TAINTED = "session_tainted"
    CREDENTIAL_PATH_READ_IN_SESSION = "credential_path_read_in_session"
    SECRET_IN_ARGUMENTS = "secret_in_arguments"
    EGRESS_TO_UNKNOWN_HOST = "egress_to_unknown_host"
    WRITE_TO_PRODUCTION = "write_to_production"
    IRREVERSIBLE_OPERATION = "irreversible_operation"
    UNDECLARED_CAPABILITY = "undeclared_capability"
    FIRST_SEEN_CAPABILITY_FOR_VERSION = "first_seen_capability_for_version"
    UNPARSEABLE_ARGUMENTS = "unparseable_arguments"
    UNATTESTED_INSTANCE = "unattested_instance"
    ELEVATED_DELEGATION_DEPTH = "elevated_delegation_depth"
    OFF_HOURS = "off_hours"
    UNKNOWN = "unknown"


class SessionTaint(StrEnum):
    """Monotonic in ``agent_sessions``: a session never becomes clean again."""

    CLEAN = "clean"
    TAINTED = "tainted"
    TAINTED_WITH_SECRETS = "tainted_with_secrets"


class Harness(StrEnum):
    """Kept identical to ``agent_instances.harness`` in `0023`.

    Two vocabularies for one fact is how a fleet view and a ledger view come to disagree
    about which harnesses exist in the estate.
    """

    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    COPILOT = "copilot"
    CODEX = "codex"
    GEMINI_CLI = "gemini_cli"
    LANGGRAPH = "langgraph"
    SDK = "sdk"
    CI = "ci"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class DownstreamMutationKind(StrEnum):
    """The SDLC join: this action became this commit, in this release."""

    COMMIT = "commit"
    PULL_REQUEST = "pull_request"
    TICKET = "ticket"
    CLOUD_RESOURCE = "cloud_resource"
    PACKAGE_VERSION = "package_version"
    DEPLOYMENT = "deployment"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------------
# Argument facets
# ---------------------------------------------------------------------------------
# The allow-list, mirroring ``agent_action_facets_valid()`` in `0024`. Answers Q-I from
# `design/15` §10 at the boundary: binary, flags, hosts, path *roots*, SQL verbs and
# tables. No shell grammar, and no key that could hold an argument value.
#
# Bounds here are tighter than the database's, in the same direction and for the same
# reason as `0017`'s ``detail`` check: Pydantic measures characters, ``pg_column_size``
# measures jsonb's binary layout, and equal numbers would make some records fail inside
# Postgres after passing validation. A rejection should be a 422 that names the field,
# not a constraint violation from the middle of a batch.

#: Short bounded strings: a command binary, an HTTP method, a hostname, a repository
#: name. Never a value an argument could carry.
FACET_TEXT_KEYS: frozenset[str] = frozenset(
    {
        "binary",
        "method",
        "scheme",
        "host",
        "repo",
        "branch",
        "vcs_operation",
        "registry",
        "package",
        "cloud_provider",
        "cloud_service",
        "cloud_operation",
    }
)

#: Counts and shapes. A depth or a length says how big the thing was without saying what
#: it contained.
FACET_NUMBER_KEYS: frozenset[str] = frozenset(
    {"argv_count", "port", "url_path_depth", "byte_length"}
)

#: Short string arrays. ``path_roots`` is roots only — ``/etc``, ``~/.aws`` — so a full
#: path is not representable; ``path_classes`` is the classification that drives policy.
FACET_ARRAY_KEYS: frozenset[str] = frozenset(
    {"argv_flags", "path_roots", "path_classes", "sql_verbs", "sql_tables"}
)

FACET_KEYS: frozenset[str] = FACET_TEXT_KEYS | FACET_NUMBER_KEYS | FACET_ARRAY_KEYS

MAX_FACET_TEXT_CHARS = 256
MAX_FACET_ARRAY_ITEMS = 32
MAX_FACET_ITEM_CHARS = 64
#: The database caps ``pg_column_size(argument_facets)`` at 4096. Half that here, on the
#: compact JSON encoding, because the two are close but not the same quantity.
MAX_FACET_BYTES = 2048


def _validate_facets(facets: dict[str, Any]) -> dict[str, Any]:
    """Allow-list, type-check and length-bound the facet map.

    An unrecognised key is an error, not a convenient extension point. The failure mode
    this prevents is a facet map that grows one well-meaning commit at a time until it is
    a payload, at which point the content-freedom claim is gone and nobody noticed.
    """
    for key, value in facets.items():
        if key in FACET_TEXT_KEYS:
            if not isinstance(value, str):
                raise ValueError(f"facet '{key}' must be a string")
            if len(value) > MAX_FACET_TEXT_CHARS:
                raise ValueError(f"facet '{key}' is longer than {MAX_FACET_TEXT_CHARS} characters")
        elif key in FACET_NUMBER_KEYS:
            # ``bool`` is an ``int`` in Python and is not a count.
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"facet '{key}' must be a number")
        elif key in FACET_ARRAY_KEYS:
            if not isinstance(value, list):
                raise ValueError(f"facet '{key}' must be an array of strings")
            if len(value) > MAX_FACET_ARRAY_ITEMS:
                raise ValueError(f"facet '{key}' carries more than {MAX_FACET_ARRAY_ITEMS} items")
            for item in value:
                if not isinstance(item, str):
                    raise ValueError(f"facet '{key}' must contain only strings")
                if len(item) > MAX_FACET_ITEM_CHARS:
                    raise ValueError(
                        f"facet '{key}' has an item longer than {MAX_FACET_ITEM_CHARS} characters"
                    )
        else:
            raise ValueError(
                f"facet '{key}' is not in the allow-list; "
                "arguments are recorded as a digest, never as content"
            )

    encoded = len(json.dumps(facets, separators=(",", ":"), sort_keys=True).encode())
    if encoded > MAX_FACET_BYTES:
        raise ValueError(f"facets serialise to {encoded} bytes, over the {MAX_FACET_BYTES} limit")
    return facets


ArgumentFacets = Annotated[dict[str, Any], AfterValidator(_validate_facets)]


# ---------------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------------


class _Section(BaseModel):
    """Base for every envelope section. ``extra="forbid"`` is the privacy control."""

    model_config = ConfigDict(extra="forbid")


class ActionSubject(_Section):
    """Who did it, through what, on whose authority — `design/14` §1.

    ``human_member_id`` is required while ``agent_id`` is not, and the asymmetry is
    deliberate. An action nobody can be asked about is not evidence, so it is refused
    here rather than written as an unattributable row. An action by an *unregistered*
    agent is a shadow-agent discovery, which is one of the things the ledger is for, so
    it must never be blocked (`design/14` §9).
    """

    human_member_id: UUID
    root_human_basis: RootHumanBasis

    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    composition_digest: Sha256Hex | None = None

    instance_id: UUID | None = None
    session_id: UUID | None = None
    task_id: UUID | None = None

    parent_instance_id: UUID | None = None
    delegation_depth: int = Field(default=0, ge=0, le=MAX_DELEGATION_DEPTH)


class ActionCapability(_Section):
    """What was invoked.

    ``operation`` is the verb, bounded and lower-cased: ``exec``, ``get``, ``post``,
    ``read``, ``volume_delete``. Not a closed set — argv and cloud API operation spaces
    are open — but shaped and short, so it cannot carry a command line.
    """

    kind: CapabilityKind
    operation: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.:-]*$")
    id: UUID | None = None
    digest: Sha256Hex | None = None
    risk_class: RiskClass = RiskClass.UNKNOWN
    write: bool = False
    irreversible: bool = False


class ActionResource(_Section):
    """What it touched, by classification and digest.

    There is no ``identifier`` field, unlike `design/15` §9's sketch. An investigator
    needs to know that forty actions touched the *same* resource, which ``digest``
    answers; the identifier itself, where it is safe to keep at all, is a bounded facet
    such as ``host`` or ``repo``. A free ``identifier`` column is a full path or a
    connection string in every estate that has one.
    """

    kind: ResourceKind = ResourceKind.UNKNOWN
    resource_class: ResourceClass = ResourceClass.UNKNOWN
    digest: Sha256Hex | None = None
    destination_class: DestinationClass = DestinationClass.NONE
    data_classes: list[DataClass] = Field(default_factory=list, max_length=16)


class ActionArguments(_Section):
    """A digest and an allow-listed facet map. Never the arguments."""

    digest: Sha256Hex | None = None
    facets: ArgumentFacets = Field(default_factory=dict)
    truncated: bool = False


class ActionDecision(_Section):
    """What the platform did about it, and how much that claim is worth."""

    outcome: ActionOutcome
    enforcement_grade: EnforcementGrade
    reason_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z][a-z0-9_.]*$")
    policy_id: UUID | None = None
    policy_version: int | None = Field(default=None, ge=0)
    matched_grant_id: UUID | None = None
    approval_id: UUID | None = None
    risk_signals: list[RiskSignal] = Field(default_factory=list, max_length=16)
    latency_added_ms: int | None = Field(default=None, ge=0)

    @property
    def effective_grade(self) -> EnforcementGrade:
        """``unknown`` reads as ``E``. Never compare ``enforcement_grade`` directly."""
        return effective_enforcement_grade(self.enforcement_grade)


class ActionCredential(_Section):
    """A lease reference and nothing else.

    The broker and ``credential_leases`` are V1's. This reference is what makes "which
    credential did this action use, and what else did that credential do" one query when
    they arrive, without the MVP holding an audience, a scope or a proof method it has no
    way to verify.
    """

    lease_id: UUID | None = None


class ActionContext(_Section):
    """The session's state at the moment of the action."""

    session_taint: SessionTaint = SessionTaint.CLEAN
    harness: Harness = Harness.UNKNOWN


class ActionProvenance(_Section):
    """Where the row came from, and whether the stream is intact.

    ``prev_event_hash`` chains per collector. A gap is visible; a deleted row is not.
    That is what makes evidence *suppression* detectable rather than merely making
    tampering hard (threat model AP-9).
    """

    collector_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.:-]*$")
    collector_version: str = Field(min_length=1, max_length=32)
    event_hash: Sha256Hex
    prev_event_hash: Sha256Hex | None = None
    source_event_id: str | None = Field(default=None, max_length=200)


class ActionCallOutcome(_Section):
    """What came back. Sizes and a status, never a body."""

    upstream_status: int | None = Field(default=None, ge=0, le=999)
    bytes_in: int | None = Field(default=None, ge=0)
    bytes_out: int | None = Field(default=None, ge=0)
    downstream_mutation_kind: DownstreamMutationKind | None = None
    downstream_mutation_ref: str | None = Field(default=None, max_length=200)


class ActionEnvelope(_Section):
    """One capability invocation, as a collector reports it.

    The cross-section rules below are the ones that cannot live on a single field. Each
    has a twin CHECK in `0024`, because a boundary validator protects the API and a
    constraint protects the table, and the ledger is reachable by migration and by
    backfill as well as by HTTP.
    """

    # ``schema`` is the wire name from `design/15` §9 and shadows a Pydantic v1 method
    # name, so the field is ``schema_id`` and the alias carries the wire spelling.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: SchemaId = Field(alias="schema", default=SCHEMA_ID)
    event_id: UUID
    occurred_at: Rfc3339
    environment: LifecycleState

    subject: ActionSubject
    capability: ActionCapability
    resource: ActionResource = Field(default_factory=ActionResource)
    arguments: ActionArguments = Field(default_factory=ActionArguments)
    decision: ActionDecision
    credential: ActionCredential = Field(default_factory=ActionCredential)
    context: ActionContext = Field(default_factory=ActionContext)
    provenance: ActionProvenance
    outcome: ActionCallOutcome = Field(default_factory=ActionCallOutcome)

    @model_validator(mode="after")
    def _enforcing_outcome_needs_a_grade(self) -> Self:
        """An intervention at grade E is a contradiction.

        E means the action was not covered, so nothing can have refused, masked or
        rerouted it, and ``unknown`` reads as E. This is the check that stops the console
        showing protection that did not happen.

        Grade D is allowed. D is "observed afterwards", and a vendor control that denied
        something before we heard about it is a real denial we did not perform — the
        grade already says so, and losing the row would be worse than recording it.
        """
        if (
            self.decision.outcome in ENFORCING_OUTCOMES
            and self.decision.effective_grade is EnforcementGrade.E
        ):
            raise ValueError(
                f"outcome '{self.decision.outcome}' claims enforcement at grade "
                f"'{self.decision.enforcement_grade}', which means not covered"
            )
        return self

    @model_validator(mode="after")
    def _downstream_mutation_is_paired(self) -> Self:
        """A reference with no kind is unjoinable; a kind with no reference is a rumour."""
        has_kind = self.outcome.downstream_mutation_kind is not None
        has_ref = self.outcome.downstream_mutation_ref is not None
        if has_kind != has_ref:
            raise ValueError(
                "downstream_mutation_kind and downstream_mutation_ref are set together, "
                "or neither is"
            )
        return self

    @model_validator(mode="after")
    def _delegation_depth_matches_parent(self) -> Self:
        """Depth and parentage are one fact stored twice, so they must agree.

        Mirrors ``agent_instances_depth_matches_parent`` in `0023`. A root instance
        reporting depth 3 makes the delegation chain unwalkable from either end.
        """
        has_parent = self.subject.parent_instance_id is not None
        if has_parent != (self.subject.delegation_depth > 0):
            raise ValueError(
                "delegation_depth must be 0 for a root instance and non-zero with a parent"
            )
        return self
