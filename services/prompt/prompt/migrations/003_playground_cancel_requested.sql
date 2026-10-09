ALTER TABLE prompt.playground_runs
    DROP CONSTRAINT IF EXISTS playground_runs_status_check;

ALTER TABLE prompt.playground_runs
    ADD CONSTRAINT playground_runs_status_check CHECK (
        status IN ('pending', 'running', 'cancel_requested', 'completed', 'failed', 'cancelled')
    );
