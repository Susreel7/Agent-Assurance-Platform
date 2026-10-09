CREATE SCHEMA IF NOT EXISTS evaluate;

CREATE TABLE IF NOT EXISTS evaluate.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluate.datasets (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    dataset_key TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT datasets_org_project_key UNIQUE (organization_id, project_id, dataset_key)
);

CREATE INDEX IF NOT EXISTS idx_datasets_org_project ON evaluate.datasets (organization_id, project_id);

CREATE TABLE IF NOT EXISTS evaluate.dataset_revisions (
    id UUID PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES evaluate.datasets (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    revision_number INTEGER NOT NULL,
    manifest_digest TEXT NOT NULL,
    example_count INTEGER NOT NULL DEFAULT 0,
    split_tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    CONSTRAINT dataset_revisions_unique UNIQUE (dataset_id, revision_number)
);

CREATE INDEX IF NOT EXISTS idx_dataset_revisions_org ON evaluate.dataset_revisions (organization_id, project_id);

CREATE TABLE IF NOT EXISTS evaluate.examples (
    id UUID PRIMARY KEY,
    dataset_revision_id UUID NOT NULL REFERENCES evaluate.dataset_revisions (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    example_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    split_name TEXT NOT NULL DEFAULT 'default',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_digest TEXT NOT NULL,
    source_trace_id TEXT,
    dedupe_digest TEXT,
    has_encrypted_payload BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT examples_revision_key UNIQUE (dataset_revision_id, example_key)
);

CREATE INDEX IF NOT EXISTS idx_examples_revision ON evaluate.examples (dataset_revision_id, ordinal);

CREATE TABLE IF NOT EXISTS evaluate.example_bodies (
    example_id UUID PRIMARY KEY REFERENCES evaluate.examples (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    input_inline JSONB,
    reference_output_inline JSONB,
    input_object_ref TEXT,
    reference_output_object_ref TEXT,
    encryption_key_ref TEXT,
    ciphertext BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluate.evaluators (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    evaluator_key TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    CONSTRAINT evaluators_org_key UNIQUE (organization_id, project_id, evaluator_key)
);

CREATE INDEX IF NOT EXISTS idx_evaluators_org ON evaluate.evaluators (organization_id, project_id);

CREATE TABLE IF NOT EXISTS evaluate.evaluator_revisions (
    id UUID PRIMARY KEY,
    evaluator_id UUID NOT NULL REFERENCES evaluate.evaluators (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    revision_number INTEGER NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    config_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    CONSTRAINT evaluator_revisions_unique UNIQUE (evaluator_id, revision_number)
);

CREATE TABLE IF NOT EXISTS evaluate.experiments (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    experiment_key TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'pending', 'running', 'completed', 'failed', 'cancelled', 'partial')
    ),
    dataset_revision_id UUID NOT NULL REFERENCES evaluate.dataset_revisions (id) ON DELETE RESTRICT,
    baseline_experiment_id UUID REFERENCES evaluate.experiments (id) ON DELETE RESTRICT,
    spec JSONB NOT NULL,
    spec_digest TEXT NOT NULL,
    seed INTEGER NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 1,
    concurrency INTEGER NOT NULL DEFAULT 1,
    budget_usd NUMERIC(12, 6),
    spent_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
    progress JSONB NOT NULL DEFAULT '{}'::jsonb,
    aggregates JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    CONSTRAINT experiments_org_key UNIQUE (organization_id, project_id, experiment_key)
);

CREATE INDEX IF NOT EXISTS idx_experiments_org_status ON evaluate.experiments (organization_id, project_id, status);

CREATE TABLE IF NOT EXISTS evaluate.experiment_results (
    id UUID PRIMARY KEY,
    experiment_id UUID NOT NULL REFERENCES evaluate.experiments (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    example_id UUID NOT NULL REFERENCES evaluate.examples (id) ON DELETE RESTRICT,
    repetition_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'skipped', 'cancelled')
    ),
    trace_id TEXT,
    output_digest TEXT,
    latency_ms INTEGER,
    cost_usd NUMERIC(12, 6),
    scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT experiment_results_unique UNIQUE (experiment_id, example_id, repetition_index)
);

CREATE INDEX IF NOT EXISTS idx_experiment_results_exp ON evaluate.experiment_results (experiment_id, status);

CREATE TABLE IF NOT EXISTS evaluate.jobs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'leased', 'running', 'completed', 'failed', 'cancelled', 'dead')
    ),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    lease_owner TEXT,
    lease_until TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT jobs_idempotency UNIQUE (organization_id, project_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_jobs_claim ON evaluate.jobs (status, lease_until, created_at)
    WHERE status IN ('pending', 'leased');

CREATE TABLE IF NOT EXISTS evaluate.scores (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('run', 'span', 'trace', 'session', 'experiment_result')),
    target_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('numeric', 'boolean', 'categorical')),
    value_numeric NUMERIC,
    value_boolean BOOLEAN,
    value_categorical TEXT,
    source TEXT NOT NULL CHECK (source IN ('human', 'automated')),
    evaluator_revision_id UUID REFERENCES evaluate.evaluator_revisions (id) ON DELETE RESTRICT,
    explanation TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    supersedes_score_id UUID REFERENCES evaluate.scores (id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scores_target ON evaluate.scores (organization_id, project_id, target_type, target_id);

CREATE TABLE IF NOT EXISTS evaluate.score_corrections (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    original_score_id UUID NOT NULL REFERENCES evaluate.scores (id) ON DELETE RESTRICT,
    corrected_score_id UUID NOT NULL REFERENCES evaluate.scores (id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluate.online_rules (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    rule_key TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    filter JSONB NOT NULL DEFAULT '{}'::jsonb,
    sample_rate NUMERIC(5, 4) NOT NULL DEFAULT 0.01,
    sample_hash_salt TEXT NOT NULL,
    evaluator_revision_ids UUID[] NOT NULL DEFAULT '{}',
    budget_usd NUMERIC(12, 6),
    spent_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
    max_concurrency INTEGER NOT NULL DEFAULT 2,
    circuit_open_until TIMESTAMPTZ,
    actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT online_rules_org_key UNIQUE (organization_id, project_id, rule_key)
);

CREATE TABLE IF NOT EXISTS evaluate.online_rule_cursors (
    rule_id UUID PRIMARY KEY REFERENCES evaluate.online_rules (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    poll_cursor TEXT NOT NULL DEFAULT '',
    last_event_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluate.online_eval_jobs (
    id UUID PRIMARY KEY,
    rule_id UUID NOT NULL REFERENCES evaluate.online_rules (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    trace_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    idempotency_key TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT online_eval_jobs_idem UNIQUE (organization_id, project_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS evaluate.annotation_queues (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    queue_key TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    item_filter JSONB NOT NULL DEFAULT '{}'::jsonb,
    rubric JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewers_required INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    CONSTRAINT annotation_queues_org_key UNIQUE (organization_id, project_id, queue_key)
);

CREATE TABLE IF NOT EXISTS evaluate.annotation_items (
    id UUID PRIMARY KEY,
    queue_id UUID NOT NULL REFERENCES evaluate.annotation_queues (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    item_type TEXT NOT NULL CHECK (item_type IN ('trace', 'span', 'session', 'pairwise')),
    reference_id TEXT NOT NULL,
    pairwise_reference_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'completed', 'skipped')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT annotation_items_unique UNIQUE (queue_id, item_type, reference_id, pairwise_reference_id)
);

CREATE INDEX IF NOT EXISTS idx_annotation_items_queue ON evaluate.annotation_items (queue_id, status);

CREATE TABLE IF NOT EXISTS evaluate.annotation_assignments (
    id UUID PRIMARY KEY,
    item_id UUID NOT NULL REFERENCES evaluate.annotation_items (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    assignee TEXT NOT NULL,
    lease_until TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT annotation_assignments_item_assignee UNIQUE (item_id, assignee)
);

CREATE TABLE IF NOT EXISTS evaluate.annotation_submissions (
    id UUID PRIMARY KEY,
    item_id UUID NOT NULL REFERENCES evaluate.annotation_items (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    assignee TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('submit', 'skip')),
    scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    comments TEXT NOT NULL DEFAULT '',
    rubric_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluate.release_gates (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    gate_key TEXT NOT NULL,
    baseline_experiment_id UUID REFERENCES evaluate.experiments (id) ON DELETE RESTRICT,
    thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    CONSTRAINT release_gates_org_key UNIQUE (organization_id, project_id, gate_key)
);

CREATE TABLE IF NOT EXISTS evaluate.release_gate_evaluations (
    id UUID PRIMARY KEY,
    gate_id UUID NOT NULL REFERENCES evaluate.release_gates (id) ON DELETE RESTRICT,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    candidate_experiment_id UUID NOT NULL REFERENCES evaluate.experiments (id) ON DELETE RESTRICT,
    passed BOOLEAN NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
