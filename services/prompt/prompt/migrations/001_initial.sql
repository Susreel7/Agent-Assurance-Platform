CREATE SCHEMA IF NOT EXISTS prompt;

CREATE TABLE IF NOT EXISTS prompt.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prompt.artifacts (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    artifact_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('prompt', 'rule', 'skill', 'context')),
    display_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT artifacts_org_project_key UNIQUE (organization_id, project_id, artifact_key)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_org_project ON prompt.artifacts (organization_id, project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON prompt.artifacts (organization_id, project_id, kind);

CREATE TABLE IF NOT EXISTS prompt.revisions (
    id UUID PRIMARY KEY,
    artifact_id UUID NOT NULL REFERENCES prompt.artifacts (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    revision_number INTEGER NOT NULL,
    parent_revision_id UUID REFERENCES prompt.revisions (id) ON DELETE RESTRICT,
    is_draft BOOLEAN NOT NULL DEFAULT FALSE,
    content_digest TEXT NOT NULL,
    schema_digest TEXT,
    config_digest TEXT,
    semantic_version TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    encryption_key_ref TEXT NOT NULL,
    secret_scan_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    CONSTRAINT revisions_artifact_number UNIQUE (artifact_id, revision_number)
);

CREATE INDEX IF NOT EXISTS idx_revisions_org_project ON prompt.revisions (organization_id, project_id);
CREATE INDEX IF NOT EXISTS idx_revisions_artifact ON prompt.revisions (artifact_id, revision_number DESC);

CREATE TABLE IF NOT EXISTS prompt.revision_bodies (
    revision_id UUID PRIMARY KEY REFERENCES prompt.revisions (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    ciphertext BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prompt.labels (
    id UUID PRIMARY KEY,
    artifact_id UUID NOT NULL REFERENCES prompt.artifacts (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    label_name TEXT NOT NULL,
    revision_id UUID NOT NULL REFERENCES prompt.revisions (id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT NOT NULL,
    CONSTRAINT labels_artifact_name UNIQUE (artifact_id, label_name)
);

CREATE INDEX IF NOT EXISTS idx_labels_org_project ON prompt.labels (organization_id, project_id);

CREATE TABLE IF NOT EXISTS prompt.label_history (
    id UUID PRIMARY KEY,
    artifact_id UUID NOT NULL REFERENCES prompt.artifacts (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    label_name TEXT NOT NULL,
    from_revision_id UUID REFERENCES prompt.revisions (id) ON DELETE RESTRICT,
    to_revision_id UUID NOT NULL REFERENCES prompt.revisions (id) ON DELETE RESTRICT,
    label_version INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_label_history_artifact ON prompt.label_history (artifact_id, created_at DESC);

CREATE TABLE IF NOT EXISTS prompt.playground_runs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('sync', 'stream', 'compare', 'replay')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    resolved_revision_ids UUID[] NOT NULL DEFAULT '{}',
    model_alias TEXT,
    router_request_id TEXT,
    router_trace JSONB NOT NULL DEFAULT '{}'::jsonb,
    variables JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_digest TEXT,
    output_digest TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_playground_runs_org_project ON prompt.playground_runs (
    organization_id, project_id, created_at DESC
);

CREATE TABLE IF NOT EXISTS prompt.audit_events (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID NOT NULL,
    actor TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_org_project_time ON prompt.audit_events (
    organization_id, project_id, created_at DESC
);
