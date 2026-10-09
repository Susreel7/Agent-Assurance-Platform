-- Phase 5 execution/session/actor correlation dimensions.

ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS invocation_source LowCardinality(String);
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS application_name LowCardinality(String);
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS client_name LowCardinality(String);
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS request_id String;
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS replay_of_execution_id String;
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS replay_reason String;
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS repository_ref String;
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS branch_ref String;
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS commit_sha String;
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS deployment_name LowCardinality(String);
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS region_name LowCardinality(String);
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS runtime_name LowCardinality(String);
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS framework_version LowCardinality(String);
ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS parent_trace_id String;

ALTER TABLE observe.execution_index ADD COLUMN IF NOT EXISTS parent_execution_id String;
ALTER TABLE observe.execution_index ADD COLUMN IF NOT EXISTS parent_trace_id String;
ALTER TABLE observe.execution_index ADD COLUMN IF NOT EXISTS invocation_source LowCardinality(String);
ALTER TABLE observe.execution_index ADD COLUMN IF NOT EXISTS application_name LowCardinality(String);
ALTER TABLE observe.execution_index ADD COLUMN IF NOT EXISTS client_name LowCardinality(String);
ALTER TABLE observe.execution_index ADD COLUMN IF NOT EXISTS request_id String;
ALTER TABLE observe.execution_index ADD COLUMN IF NOT EXISTS replay_of_execution_id String;
ALTER TABLE observe.execution_index ADD COLUMN IF NOT EXISTS framework LowCardinality(String);
