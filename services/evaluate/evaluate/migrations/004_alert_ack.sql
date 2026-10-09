ALTER TABLE evaluate.alert_deliveries
    ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;
