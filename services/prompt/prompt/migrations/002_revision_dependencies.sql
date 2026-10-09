CREATE TABLE IF NOT EXISTS prompt.revision_dependencies (
    revision_id UUID NOT NULL REFERENCES prompt.revisions (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    dependency_artifact_key TEXT NOT NULL,
    dependency_label TEXT,
    dependency_revision_id UUID REFERENCES prompt.revisions (id) ON DELETE RESTRICT,
    CONSTRAINT revision_dependencies_pk PRIMARY KEY (revision_id, dependency_artifact_key)
);

CREATE INDEX IF NOT EXISTS idx_revision_dependencies_key ON prompt.revision_dependencies (
    organization_id, project_id, dependency_artifact_key
);
