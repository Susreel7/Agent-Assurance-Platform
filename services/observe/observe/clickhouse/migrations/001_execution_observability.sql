-- Additive execution observability columns and tables (idempotent; init.sql remains base)

ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS execution_id String DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS parent_execution_id String DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS observation_type LowCardinality(String) DEFAULT 'unknown';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS environment_id String DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS agent_version_id String DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS initiating_user_id String DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS effective_actor_id String DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS effective_actor_type LowCardinality(String) DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS user_session_id String DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS provider LowCardinality(String) DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS sdk_name LowCardinality(String) DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS sdk_version LowCardinality(String) DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS mcp_server LowCardinality(String) DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS mcp_method LowCardinality(String) DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS retry_attempt UInt16 DEFAULT 0;
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS graph_node_id String DEFAULT '';
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS graph_node_path String DEFAULT '';

ALTER TABLE observe.spans ADD INDEX IF NOT EXISTS idx_observation_type observation_type TYPE minmax GRANULARITY 4;
ALTER TABLE observe.spans ADD INDEX IF NOT EXISTS idx_execution_id execution_id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE observe.spans ADD INDEX IF NOT EXISTS idx_initiating_user initiating_user_id TYPE bloom_filter GRANULARITY 4;

CREATE TABLE IF NOT EXISTS observe.events
(
    organization_id UUID,
    project_id UUID,
    event_uid String,
    execution_id String,
    trace_id String,
    span_id FixedString(16),
    event_type LowCardinality(String),
    observation_type LowCardinality(String),
    event_time DateTime64(9, 'UTC'),
    status LowCardinality(String),
    initiating_user_id String,
    effective_actor_id String,
    agent_id String,
    model LowCardinality(String),
    tool_name LowCardinality(String),
    sdk_name LowCardinality(String),
    mcp_server LowCardinality(String),
    mcp_method LowCardinality(String),
    sequence UInt32,
    attributes Map(String, String),
    version UInt64,
    inserted_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(event_time)
ORDER BY (organization_id, project_id, trace_id, event_uid)
TTL toDateTime(event_time) + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS observe.execution_edges
(
    organization_id UUID,
    project_id UUID,
    execution_id String,
    trace_id FixedString(32),
    from_span_id FixedString(16),
    to_span_id FixedString(16),
    edge_type LowCardinality(String),
    version UInt64,
    inserted_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(inserted_at)
ORDER BY (organization_id, project_id, execution_id, edge_type, from_span_id, to_span_id);

CREATE TABLE IF NOT EXISTS observe.execution_index
(
    organization_id UUID,
    project_id UUID,
    execution_id String,
    execution_type LowCardinality(String),
    trace_id FixedString(32),
    root_span_id FixedString(16),
    session_id String,
    user_session_id String,
    environment_id String,
    agent_id String,
    agent_version_id String,
    initiating_user_id String,
    status LowCardinality(String),
    start_time DateTime64(9, 'UTC'),
    end_time DateTime64(9, 'UTC'),
    duration_ms Float64,
    span_count UInt32,
    node_count UInt32,
    generation_count UInt32,
    tool_count UInt32,
    sdk_count UInt32,
    error_count UInt32,
    retry_count UInt32,
    input_tokens UInt64,
    output_tokens UInt64,
    total_cost_micros Int64,
    provider LowCardinality(String),
    sdk_name LowCardinality(String),
    mcp_server LowCardinality(String),
    is_live UInt8,
    is_partial UInt8,
    version UInt64,
    inserted_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(start_time)
ORDER BY (organization_id, project_id, start_time, execution_id)
TTL toDateTime(start_time) + INTERVAL 90 DAY;

ALTER TABLE observe.execution_index ADD INDEX IF NOT EXISTS idx_exec_session session_id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE observe.execution_index ADD INDEX IF NOT EXISTS idx_exec_user initiating_user_id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE observe.execution_index ADD INDEX IF NOT EXISTS idx_exec_agent agent_id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE observe.execution_index ADD INDEX IF NOT EXISTS idx_exec_status status TYPE minmax GRANULARITY 4;
