-- Project-level Observe sampling controls. Edge collectors may cache this policy;
-- execution rows retain the effective sampling metadata used for analytics labels.

CREATE TABLE IF NOT EXISTS observe.sampling_policies (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    head_sample_rate DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    tail_keep_errors BOOLEAN NOT NULL DEFAULT true,
    tail_keep_retries BOOLEAN NOT NULL DEFAULT true,
    tail_keep_high_latency BOOLEAN NOT NULL DEFAULT true,
    high_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 10000,
    max_traces_per_minute INT,
    revision BIGINT NOT NULL DEFAULT 1,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id),
    CONSTRAINT sampling_head_rate CHECK (head_sample_rate >= 0 AND head_sample_rate <= 1),
    CONSTRAINT sampling_latency_positive CHECK (high_latency_ms > 0),
    CONSTRAINT sampling_rate_limit_positive CHECK (
        max_traces_per_minute IS NULL OR max_traces_per_minute > 0
    )
);

ALTER TABLE observe.agent_executions
    ADD COLUMN IF NOT EXISTS sample_rate DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS sampling_decision TEXT NOT NULL DEFAULT 'recorded';

CREATE INDEX IF NOT EXISTS idx_agent_executions_analytics_time
    ON observe.agent_executions (organization_id, project_id, start_time DESC)
    INCLUDE (status, duration_ms, total_cost_micros, initiating_user_id, agent_id);
