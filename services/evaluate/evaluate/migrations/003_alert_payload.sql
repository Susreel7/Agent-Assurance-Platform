ALTER TABLE evaluate.alert_deliveries
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;
