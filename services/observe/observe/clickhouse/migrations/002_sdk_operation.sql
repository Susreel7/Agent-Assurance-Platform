-- SDK operation dimension (additive)

ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS sdk_operation LowCardinality(String) DEFAULT '';

ALTER TABLE observe.events ADD COLUMN IF NOT EXISTS sdk_operation LowCardinality(String) DEFAULT '';
