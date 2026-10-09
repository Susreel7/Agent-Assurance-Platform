-- Phase 2: agent execution metadata, users, projection outbox (additive; 001/002 unchanged)

ALTER TABLE observe.ingest_manifests
    ADD COLUMN IF NOT EXISTS envelope_kind TEXT NOT NULL DEFAULT 'traces',
    ADD COLUMN IF NOT EXISTS source_wire_digest TEXT,
    ADD COLUMN IF NOT EXISTS log_record_count INT NOT NULL DEFAULT 0;

ALTER TABLE observe.ingest_manifests
    DROP CONSTRAINT IF EXISTS ingest_manifests_envelope_kind_check;

ALTER TABLE observe.ingest_manifests
    ADD CONSTRAINT ingest_manifests_envelope_kind_check CHECK (
        envelope_kind IN ('traces', 'logs')
    );

ALTER TABLE observe.payload_refs
    ADD COLUMN IF NOT EXISTS payload_id UUID,
    ADD COLUMN IF NOT EXISTS redaction_state TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS content_policy_revision INT;

UPDATE observe.payload_refs SET payload_id = id WHERE payload_id IS NULL;

ALTER TABLE observe.payload_refs
    ALTER COLUMN payload_id SET DEFAULT gen_random_uuid(),
    ALTER COLUMN payload_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_payload_refs_payload_id
    ON observe.payload_refs (organization_id, project_id, payload_id);

ALTER TABLE observe.session_metadata
    ADD COLUMN IF NOT EXISTS user_session_id TEXT,
    ADD COLUMN IF NOT EXISTS initiating_user_id TEXT,
    ADD COLUMN IF NOT EXISTS execution_count INT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS observe.agent_executions (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    execution_id TEXT NOT NULL,
    execution_type TEXT NOT NULL DEFAULT 'agent',
    trace_id TEXT NOT NULL,
    root_span_id TEXT,
    parent_execution_id TEXT,
    parent_trace_id TEXT,
    session_id TEXT,
    user_session_id TEXT,
    environment_id TEXT,
    agent_id TEXT,
    agent_version_id TEXT,
    agent_name TEXT,
    agent_version TEXT,
    initiating_user_id TEXT,
    effective_actor_id TEXT,
    effective_actor_type TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    duration_ms DOUBLE PRECISION,
    span_count INT NOT NULL DEFAULT 0,
    node_count INT NOT NULL DEFAULT 0,
    generation_count INT NOT NULL DEFAULT 0,
    tool_count INT NOT NULL DEFAULT 0,
    sdk_count INT NOT NULL DEFAULT 0,
    error_count INT NOT NULL DEFAULT 0,
    retry_count INT NOT NULL DEFAULT 0,
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    total_cost_micros BIGINT NOT NULL DEFAULT 0,
    is_live BOOLEAN NOT NULL DEFAULT false,
    is_partial BOOLEAN NOT NULL DEFAULT false,
    is_malformed BOOLEAN NOT NULL DEFAULT false,
    has_cycle BOOLEAN NOT NULL DEFAULT false,
    has_late_data BOOLEAN NOT NULL DEFAULT false,
    capture_level TEXT,
    provider TEXT,
    sdk_name TEXT,
    mcp_server TEXT,
    framework TEXT,
    tags TEXT[] NOT NULL DEFAULT '{}',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, execution_id),
    CONSTRAINT agent_executions_execution_id_len CHECK (char_length(execution_id) <= 128),
    CONSTRAINT agent_executions_type_check CHECK (
        execution_type IN ('agent', 'user_activity', 'workflow')
    ),
    CONSTRAINT agent_executions_status_check CHECK (
        status IN ('queued', 'running', 'success', 'error', 'cancelled', 'open', 'partial')
    ),
    CONSTRAINT agent_executions_actor_type_check CHECK (
        effective_actor_type IS NULL
        OR effective_actor_type IN ('user', 'agent', 'service', 'unknown')
    )
);

CREATE INDEX IF NOT EXISTS idx_agent_executions_trace
    ON observe.agent_executions (organization_id, project_id, trace_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_executions_user
    ON observe.agent_executions (organization_id, project_id, initiating_user_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_executions_status
    ON observe.agent_executions (organization_id, project_id, status, start_time DESC);

CREATE TABLE IF NOT EXISTS observe.observed_users (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    display_label TEXT,
    team TEXT,
    activity_source TEXT,
    execution_count INT NOT NULL DEFAULT 0,
    generation_count INT NOT NULL DEFAULT 0,
    tool_count INT NOT NULL DEFAULT 0,
    sdk_count INT NOT NULL DEFAULT 0,
    mcp_tool_count INT NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, user_id),
    CONSTRAINT observed_users_user_id_len CHECK (char_length(user_id) <= 256)
);

CREATE TABLE IF NOT EXISTS observe.user_identity_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    binding_type TEXT NOT NULL,
    binding_value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_identity_binding_type_check CHECK (
        binding_type IN ('oidc_subject', 'app_user_id', 'external_id')
    ),
    CONSTRAINT user_identity_binding_value_len CHECK (char_length(binding_value) <= 512),
    UNIQUE (organization_id, project_id, binding_type, binding_value)
);

CREATE INDEX IF NOT EXISTS idx_user_identity_bindings_user
    ON observe.user_identity_bindings (organization_id, project_id, user_id);

CREATE TABLE IF NOT EXISTS observe.execution_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    execution_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    target_execution_id TEXT,
    target_trace_id TEXT,
    target_span_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT execution_links_type_len CHECK (char_length(link_type) <= 64),
    CONSTRAINT execution_links_execution_id_len CHECK (char_length(execution_id) <= 128)
);

CREATE INDEX IF NOT EXISTS idx_execution_links_execution
    ON observe.execution_links (organization_id, project_id, execution_id);

CREATE TABLE IF NOT EXISTS observe.payload_access_audit (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    payload_ref_id UUID,
    trace_id TEXT,
    span_id TEXT,
    field_name TEXT,
    actor_subject TEXT NOT NULL,
    access_kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT payload_access_actor_len CHECK (char_length(actor_subject) <= 256),
    CONSTRAINT payload_access_kind_check CHECK (
        access_kind IN ('metadata', 'preview', 'full')
    )
);

CREATE INDEX IF NOT EXISTS idx_payload_access_audit_project_time
    ON observe.payload_access_audit (organization_id, project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS observe.projection_outbox (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    execution_id TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'execution.terminal',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at TIMESTAMPTZ,
    CONSTRAINT projection_outbox_execution_id_len CHECK (char_length(execution_id) <= 128),
    UNIQUE (organization_id, project_id, execution_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_projection_outbox_pending
    ON observe.projection_outbox (created_at)
    WHERE dispatched_at IS NULL;

CREATE TABLE IF NOT EXISTS observe.log_record_idempotency (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    trace_id TEXT NOT NULL,
    log_record_uid TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    manifest_id UUID NOT NULL REFERENCES observe.ingest_manifests (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, trace_id, log_record_uid)
);

ALTER TABLE observe.agent_executions
    ADD COLUMN IF NOT EXISTS mcp_tool_count INT NOT NULL DEFAULT 0;

ALTER TABLE observe.agent_executions
    DROP CONSTRAINT IF EXISTS agent_executions_status_check;

ALTER TABLE observe.agent_executions
    ADD CONSTRAINT agent_executions_status_check CHECK (
        status IN (
            'queued', 'running', 'waiting', 'succeeded', 'failed', 'timed_out',
            'cancelled', 'refused', 'partial', 'unknown', 'open',
            'success', 'error'
        )
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_ingest_manifests_source_wire
    ON observe.ingest_manifests (organization_id, project_id, source_wire_digest)
    WHERE source_wire_digest IS NOT NULL AND source_wire_digest <> '';
