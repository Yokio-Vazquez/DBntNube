CREATE TABLE public.event_audit_outbox (
    operation_id VARCHAR(32) PRIMARY KEY,
    actor_id VARCHAR(120) NOT NULL,
    game_id BIGINT NOT NULL,
    event_key TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    outcome VARCHAR(20),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    CONSTRAINT event_audit_outbox_actor_valid CHECK (actor_id = 'writer'),
    CONSTRAINT event_audit_outbox_state_valid CHECK (
        (status = 'pending' AND outcome IS NULL AND completed_at IS NULL)
        OR
        (status = 'completed' AND outcome IS NOT NULL
            AND outcome IN ('success', 'conflict', 'unavailable', 'failure')
            AND completed_at IS NOT NULL)
    )
);

CREATE INDEX event_audit_outbox_pending_idx
    ON public.event_audit_outbox (requested_at)
    WHERE status = 'pending';

CREATE OR REPLACE FUNCTION guard_event_audit_outbox_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status <> 'pending'
        OR NEW.operation_id <> OLD.operation_id
        OR NEW.actor_id <> OLD.actor_id
        OR NEW.game_id <> OLD.game_id
        OR NEW.event_key <> OLD.event_key
        OR NEW.requested_at <> OLD.requested_at
        OR NEW.status <> 'completed'
    THEN
        RAISE EXCEPTION 'invalid event audit outbox transition';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER event_audit_outbox_transition
    BEFORE UPDATE ON public.event_audit_outbox
    FOR EACH ROW EXECUTE FUNCTION guard_event_audit_outbox_transition();

GRANT SELECT, INSERT, UPDATE ON public.event_audit_outbox TO cdrl_writer;
