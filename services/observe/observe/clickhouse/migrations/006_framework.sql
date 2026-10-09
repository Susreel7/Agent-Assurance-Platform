-- Preserve the explicitly reported orchestration framework when spans are reloaded.
ALTER TABLE observe.spans
    ADD COLUMN IF NOT EXISTS framework LowCardinality(String);
