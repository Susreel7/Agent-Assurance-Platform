-- observe schema: durable ingest manifests, payload refs, quarantine, trace metadata
CREATE SCHEMA IF NOT EXISTS observe;

CREATE TABLE IF NOT EXISTS observe.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS observe.ingest_manifests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    agent_id UUID,
    envelope_digest TEXT NOT NULL,
    object_key TEXT NOT NULL,
    content_encoding TEXT NOT NULL DEFAULT 'identity',
    content_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    span_count INT NOT NULL,
    rejected_span_count INT NOT NULL DEFAULT 0,
    capture_mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    locked_by TEXT,
    locked_at TIMESTAMPTZ,
    normalized_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ingest_manifests_status_check CHECK (
        status IN ('pending', 'processing', 'done', 'quarantined', 'failed')
    ),
    CONSTRAINT ingest_manifests_capture_check CHECK (
        capture_mode IN ('none', 'digest', 'redacted', 'full')
    ),
    UNIQUE (organization_id, project_id, envelope_digest)
);

CREATE INDEX IF NOT EXISTS idx_ingest_manifests_poll
    ON observe.ingest_manifests (status, created_at)
    WHERE status IN ('pending', 'processing');

CREATE INDEX IF NOT EXISTS idx_ingest_manifests_org_project
    ON observe.ingest_manifests (organization_id, project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS observe.payload_refs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    digest TEXT NOT NULL,
    object_key TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    encryption_key_ref TEXT,
    retention_deadline TIMESTAMPTZ,
    legal_hold BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, trace_id, span_id, field_name, digest)
);

CREATE INDEX IF NOT EXISTS idx_payload_refs_trace
    ON observe.payload_refs (organization_id, project_id, trace_id);

CREATE TABLE IF NOT EXISTS observe.quarantine_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    reason TEXT NOT NULL,
    envelope_digest TEXT,
    manifest_id UUID REFERENCES observe.ingest_manifests (id),
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS observe.span_idempotency (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    manifest_id UUID NOT NULL REFERENCES observe.ingest_manifests (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, trace_id, span_id)
);

CREATE TABLE IF NOT EXISTS observe.trace_metadata (
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    trace_id TEXT NOT NULL,
    session_id TEXT,
    service_name TEXT,
    agent_id TEXT,
    agent_name TEXT,
    root_span_id TEXT,
    span_count INT NOT NULL DEFAULT 0,
    is_malformed BOOLEAN NOT NULL DEFAULT false,
    has_cycle BOOLEAN NOT NULL DEFAULT false,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, trace_id)
);

CREATE INDEX IF NOT EXISTS idx_trace_metadata_session
    ON observe.trace_metadata (organization_id, project_id, session_id, last_seen_at DESC);
