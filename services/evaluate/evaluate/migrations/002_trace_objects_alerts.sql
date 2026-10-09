ALTER TABLE evaluate.experiment_results
    ADD COLUMN IF NOT EXISTS span_id TEXT,
    ADD COLUMN IF NOT EXISTS trace_link JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE evaluate.online_eval_jobs
    ADD COLUMN IF NOT EXISTS span_id TEXT,
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS evaluate.object_refs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    purpose TEXT NOT NULL,
    storage_ref TEXT NOT NULL,
    encryption_key_ref TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_object_refs_org ON evaluate.object_refs (organization_id, project_id);

CREATE TABLE IF NOT EXISTS evaluate.observe_ingest_cursors (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    poll_cursor TEXT NOT NULL DEFAULT '',
    last_event_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS evaluate.alert_deliveries (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    rule_id UUID REFERENCES evaluate.online_rules (id) ON DELETE RESTRICT,
    action_type TEXT NOT NULL,
    target TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'failed', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    last_error TEXT,
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ,
    CONSTRAINT alert_deliveries_idem UNIQUE (organization_id, project_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_alert_deliveries_pending
    ON evaluate.alert_deliveries (status, created_at)
    WHERE status = 'pending';
