"""ORM models, grouped by the migration that created them.

Models live here rather than inside a domain module because ``AGENTS.md`` fixes each
domain at four files, and because a model is frequently read by a neighbouring domain's
repository while its *service* stays private.

They are deliberately thin. No relationships, no cascades, no behaviour — those belong
in ``service.py``, and lazy loading in an async codebase produces failures that are
tedious to trace. A model here exists to give a query result a type.

The hand-written migrations are the source of truth for the schema. These declarations
mirror them, and ``tests/integration/test_model_drift.py`` asserts the two agree.

| Module | Migration | Covers |
|---|---|---|
| ``registry`` | 0001 | organisations, agents, versions, ownership, BOM, releases, jobs |
| ``company`` | 0002 | customers, contacts, frameworks, controls, engagements |
| ``evidence`` | 0003 | evidence events, Merkle batches, published checkpoints |
| ``graph`` | 0004 | graph nodes and edges, discovery sources and findings |
| ``assurance`` | 0005 | policy, findings, service levels, posture, accreditation |
| ``operations`` | 0008, 0009 | agent runs, run steps, daily tool and MCP usage |
| ``composition`` | 0010 | rule obligations, declared vs observed reconciliation |
| ``model_routing`` | 0012, 0015 | catalogue, gateway logs, router runtime |
| ``workload_identity`` | 0014 | projects, workload credentials and generations |
| ``access`` | 0017 | members, identities, teams, roles, grants, access requests |
| ``connections`` | 0017 | provider connections, secret versions, connection grants |
| ``mcp_registry`` | 0017 | MCP servers, snapshots, capabilities, grants, usage |
| ``security_audit`` | 0017 | append-only identity/access/enforcement history |
| ``auth`` | 0022 | auth providers, server-side console sessions |
| ``agent_runtime`` | 0023 | agent instances, agent sessions, agent tasks, delegations |
| ``agent_actions`` | 0024 | the content-free agent action ledger and its receipts |

``auth`` was written in `0022` and never exported here, which meant ``AuthProvider`` and
``AuthSession`` were absent from ``Base.metadata`` and therefore invisible to
``test_model_drift.py`` — the one test whose whole job is to notice that. A model that is
not registered is not checked, and the failure mode is silence. Adding a module here is
part of writing it, not a follow-up.
"""

from __future__ import annotations

from app.db.models.access import (
    AccessGrant,
    AccessRequest,
    Member,
    MemberIdentity,
    Role,
    Team,
    TeamMember,
)
from app.db.models.agent_actions import (
    AgentAction,
    AgentActionReceipt,
)
from app.db.models.agent_runtime import (
    AgentInstance,
    AgentSession,
    AgentTask,
    Delegation,
)
from app.db.models.assurance import (
    Accreditation,
    AccreditationControl,
    AccreditationPack,
    AccreditationTransition,
    AttestationRun,
    Finding,
    Policy,
    PolicyDecision,
    PolicyVersion,
    PostureScore,
    ProbeRun,
    ProbeSuite,
    SloBreach,
    SloDefinition,
    SloMeasurement,
)
from app.db.models.auth import (
    AuthProvider,
    AuthSession,
)
from app.db.models.company import (
    ControlMapping,
    Customer,
    CustomerContact,
    CustomerFramework,
    Engagement,
    EngagementAgent,
    EngagementServiceLevel,
    Framework,
    FrameworkControl,
    ObligationTemplate,
)
from app.db.models.composition import (
    CompositionReconciliation,
    CompositionRuleObligation,
)
from app.db.models.connections import (
    ConnectionGrant,
    ConnectionSecretVersion,
    ProviderConnection,
)
from app.db.models.evidence import (
    EvidenceBatch,
    EvidenceCheckpoint,
    EvidenceEvent,
)
from app.db.models.graph import (
    DiscoveryFinding,
    DiscoverySource,
    GraphEdge,
    GraphNode,
)
from app.db.models.mcp_registry import (
    McpCapability,
    McpCapabilityUsageDaily,
    McpGrant,
    McpServer,
    McpSnapshot,
)
from app.db.models.model_routing import (
    GatewayRequestLog,
    ModelCatalogAlias,
    ModelCatalogEntry,
    ModelDeployment,
    ModelRoute,
    ModelRouteTarget,
    RouterConfigSnapshot,
    RouterSigningKey,
)
from app.db.models.operations import (
    AgentRun,
    RunStep,
    ToolUsageDaily,
)
from app.db.models.registry import (
    Agent,
    AgentOwnership,
    AgentVersion,
    BomComponent,
    Job,
    Organization,
    Release,
    ReleaseChange,
)
from app.db.models.security_audit import SecurityAuditEvent
from app.db.models.workload_identity import (
    Project,
    WorkloadCredential,
    WorkloadCredentialGeneration,
)

__all__ = [
    "AccessGrant",
    "AccessRequest",
    "Accreditation",
    "AccreditationControl",
    "AccreditationPack",
    "AccreditationTransition",
    "Agent",
    "AgentAction",
    "AgentActionReceipt",
    "AgentInstance",
    "AgentOwnership",
    "AgentRun",
    "AgentSession",
    "AgentTask",
    "AgentVersion",
    "AttestationRun",
    "AuthProvider",
    "AuthSession",
    "BomComponent",
    "CompositionReconciliation",
    "CompositionRuleObligation",
    "ConnectionGrant",
    "ConnectionSecretVersion",
    "ControlMapping",
    "Customer",
    "CustomerContact",
    "CustomerFramework",
    "Delegation",
    "DiscoveryFinding",
    "DiscoverySource",
    "Engagement",
    "EngagementAgent",
    "EngagementServiceLevel",
    "EvidenceBatch",
    "EvidenceCheckpoint",
    "EvidenceEvent",
    "Finding",
    "Framework",
    "FrameworkControl",
    "GatewayRequestLog",
    "GraphEdge",
    "GraphNode",
    "Job",
    "McpCapability",
    "McpCapabilityUsageDaily",
    "McpGrant",
    "McpServer",
    "McpSnapshot",
    "Member",
    "MemberIdentity",
    "ModelCatalogAlias",
    "ModelCatalogEntry",
    "ModelDeployment",
    "ModelRoute",
    "ModelRouteTarget",
    "ObligationTemplate",
    "Organization",
    "Policy",
    "PolicyDecision",
    "PolicyVersion",
    "PostureScore",
    "ProbeRun",
    "ProbeSuite",
    "Project",
    "ProviderConnection",
    "Release",
    "ReleaseChange",
    "Role",
    "RouterConfigSnapshot",
    "RouterSigningKey",
    "RunStep",
    "SecurityAuditEvent",
    "SloBreach",
    "SloDefinition",
    "SloMeasurement",
    "Team",
    "TeamMember",
    "ToolUsageDaily",
    "WorkloadCredential",
    "WorkloadCredentialGeneration",
]
