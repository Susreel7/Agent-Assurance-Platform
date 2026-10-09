-- ClickHouse analytics store for normalized spans (no raw content).
CREATE DATABASE IF NOT EXISTS observe;

CREATE TABLE IF NOT EXISTS observe.spans
(
    organization_id UUID,
    project_id UUID,
    trace_id FixedString(32),
    span_id FixedString(16),
    parent_span_id FixedString(16),
    session_id String,
    service_name LowCardinality(String),
    agent_id String,
    agent_name LowCardinality(String),
    kind LowCardinality(String),
    operation_name String,
    source_convention LowCardinality(String),
    mapping_revision UInt16,
    status_code LowCardinality(String),
    outcome LowCardinality(String),
    model LowCardinality(String),
    tool_name LowCardinality(String),
    start_time DateTime64(9, 'UTC'),
    end_time DateTime64(9, 'UTC'),
    duration_ms Float64,
    input_tokens UInt32,
    output_tokens UInt32,
    cost_micros Int64,
    clock_skew_flag UInt8,
    is_terminal UInt8,
    version UInt64,
    tags Array(String),
    search_text String,
    inserted_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(start_time)
ORDER BY (organization_id, project_id, trace_id, span_id)
TTL toDateTime(start_time) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;

ALTER TABLE observe.spans
    MODIFY TTL toDateTime(start_time) + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS observe.trace_index
(
    organization_id UUID,
    project_id UUID,
    trace_id FixedString(32),
    session_id String,
    service_name LowCardinality(String),
    agent_id String,
    root_span_id FixedString(16),
    span_count UInt32,
    start_time DateTime64(9, 'UTC'),
    end_time DateTime64(9, 'UTC'),
    total_cost_micros Int64,
    outcome LowCardinality(String),
    version UInt64,
    inserted_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(start_time)
ORDER BY (organization_id, project_id, start_time, trace_id)
TTL toDateTime(start_time) + INTERVAL 90 DAY;

ALTER TABLE observe.trace_index ADD INDEX IF NOT EXISTS idx_session session_id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE observe.trace_index ADD INDEX IF NOT EXISTS idx_agent agent_id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE observe.spans ADD INDEX IF NOT EXISTS idx_kind kind TYPE minmax GRANULARITY 4;
ALTER TABLE observe.spans ADD INDEX IF NOT EXISTS idx_model model TYPE bloom_filter GRANULARITY 4;
