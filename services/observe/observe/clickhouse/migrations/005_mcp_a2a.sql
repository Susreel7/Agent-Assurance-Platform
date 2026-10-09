ALTER TABLE observe.spans
    ADD COLUMN IF NOT EXISTS mcp_role LowCardinality(String),
    ADD COLUMN IF NOT EXISTS mcp_request_id String,
    ADD COLUMN IF NOT EXISTS a2a_target_agent_id String,
    ADD COLUMN IF NOT EXISTS a2a_target_execution_id String,
    ADD COLUMN IF NOT EXISTS a2a_target_trace_id String;

ALTER TABLE observe.spans
    ADD INDEX IF NOT EXISTS idx_mcp_request mcp_request_id TYPE bloom_filter GRANULARITY 4;

ALTER TABLE observe.spans
    ADD INDEX IF NOT EXISTS idx_a2a_target a2a_target_execution_id TYPE bloom_filter GRANULARITY 4;
