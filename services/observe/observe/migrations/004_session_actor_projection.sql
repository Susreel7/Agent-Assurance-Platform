-- Phase 5: session/actor/replay correlation and reliable Operations projection.

ALTER TABLE observe.agent_executions
    ADD COLUMN IF NOT EXISTS invocation_source TEXT,
    ADD COLUMN IF NOT EXISTS application_name TEXT,
    ADD COLUMN IF NOT EXISTS client_name TEXT,
    ADD COLUMN IF NOT EXISTS request_id TEXT,
    ADD COLUMN IF NOT EXISTS replay_of_execution_id TEXT,
    ADD COLUMN IF NOT EXISTS replay_reason TEXT,
    ADD COLUMN IF NOT EXISTS repository_ref TEXT,
    ADD COLUMN IF NOT EXISTS branch_ref TEXT,
    ADD COLUMN IF NOT EXISTS commit_sha TEXT,
    ADD COLUMN IF NOT EXISTS deployment_name TEXT,
    ADD COLUMN IF NOT EXISTS region_name TEXT,
    ADD COLUMN IF NOT EXISTS runtime_name TEXT,
    ADD COLUMN IF NOT EXISTS framework_version TEXT;

CREATE INDEX IF NOT EXISTS idx_agent_executions_session
    ON observe.agent_executions (organization_id, project_id, session_id, start_time);

CREATE INDEX IF NOT EXISTS idx_agent_executions_request
    ON observe.agent_executions (organization_id, project_id, request_id)
    WHERE request_id IS NOT NULL;

ALTER TABLE observe.session_metadata
    ADD COLUMN IF NOT EXISTS display_name TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS environment_ids TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS agent_ids TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS start_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS duration_ms DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS span_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS node_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS generation_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tool_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sdk_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS error_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_cost_micros BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS replay_count INT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS observe.invocation_actors (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    actor_id TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    initiating_user_id TEXT,
    invocation_source TEXT,
    application_name TEXT,
    client_name TEXT,
    execution_count INT NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, actor_type, actor_id),
    CONSTRAINT invocation_actors_type_check CHECK (
        actor_type IN ('user', 'agent', 'service', 'cli', 'webhook', 'scheduled_job', 'mcp', 'a2a', 'unknown')
    ),
    CONSTRAINT invocation_actors_id_len CHECK (char_length(actor_id) <= 256)
);

ALTER TABLE observe.projection_outbox
    ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS last_error TEXT,
    ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lock_owner TEXT;

DROP INDEX IF EXISTS observe.idx_projection_outbox_pending;
CREATE INDEX IF NOT EXISTS idx_projection_outbox_pending
    ON observe.projection_outbox (next_attempt_at, created_at)
    WHERE dispatched_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_links_unique_target
    ON observe.execution_links (
        organization_id,
        project_id,
        execution_id,
        link_type,
        coalesce(target_execution_id, ''),
        coalesce(target_trace_id, ''),
        coalesce(target_span_id, '')
    );
