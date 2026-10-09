-- Phase 12: defense-in-depth tenant isolation and governed payload retention.

ALTER TABLE observe.payload_refs
    ADD COLUMN IF NOT EXISTS legal_hold_reason TEXT,
    ADD COLUMN IF NOT EXISTS legal_hold_actor TEXT,
    ADD COLUMN IF NOT EXISTS legal_hold_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retention_deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_payload_refs_retention_sweep
    ON observe.payload_refs (retention_deadline)
    WHERE object_key <> '' AND retention_deleted_at IS NULL AND legal_hold = false;

CREATE TABLE IF NOT EXISTS observe.payload_policy_audit (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL,
    project_id UUID NOT NULL,
    payload_id UUID NOT NULL,
    action TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT payload_policy_audit_action_check CHECK (
        action IN ('legal_hold_enabled', 'legal_hold_released', 'retention_deleted')
    ),
    CONSTRAINT payload_policy_audit_actor_len CHECK (char_length(actor_subject) <= 256)
);

CREATE INDEX IF NOT EXISTS idx_payload_policy_audit_payload
    ON observe.payload_policy_audit (organization_id, project_id, payload_id, created_at DESC);

-- Policies use transaction-local settings populated by the query/ingest connection
-- boundary. Background processors explicitly opt into the worker branch.
DO $$
DECLARE
    table_name TEXT;
    predicate TEXT :=
        '(current_setting(''app.observe_worker'', true) = ''on'' OR '
        || '(organization_id::text = current_setting(''app.organization_id'', true) '
        || 'AND project_id::text = current_setting(''app.project_id'', true)))';
BEGIN
    FOR table_name IN
        SELECT DISTINCT c1.table_name
        FROM information_schema.columns c1
        JOIN information_schema.columns c2
          ON c1.table_schema = c2.table_schema AND c1.table_name = c2.table_name
        WHERE c1.table_schema = 'observe'
          AND c1.column_name = 'organization_id'
          AND c2.column_name = 'project_id'
    LOOP
        EXECUTE format('ALTER TABLE observe.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE observe.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('DROP POLICY IF EXISTS observe_tenant_isolation ON observe.%I', table_name);
        EXECUTE format(
            'CREATE POLICY observe_tenant_isolation ON observe.%I '
            || 'USING (%s) WITH CHECK (%s)',
            table_name,
            predicate,
            predicate
        );
    END LOOP;
END $$;
