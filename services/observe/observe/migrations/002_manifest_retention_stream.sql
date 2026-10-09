ALTER TABLE observe.ingest_manifests
    ADD COLUMN IF NOT EXISTS payload_retention_days INT NOT NULL DEFAULT 30,
    ADD COLUMN IF NOT EXISTS payload_encryption_key_ref TEXT;

ALTER TABLE observe.span_idempotency
    ADD COLUMN IF NOT EXISTS is_terminal BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS observe.stream_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    trace_id TEXT,
    span_id TEXT,
    cursor_token TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stream_events_poll
    ON observe.stream_events (organization_id, project_id, id);

CREATE TABLE IF NOT EXISTS observe.session_metadata (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    session_id TEXT NOT NULL,
    trace_count INT NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, session_id)
);
