ALTER TABLE observe.spans
    ADD COLUMN IF NOT EXISTS sample_rate Float64 DEFAULT 1.0;

ALTER TABLE observe.execution_index
    ADD COLUMN IF NOT EXISTS sample_rate Float64 DEFAULT 1.0;
