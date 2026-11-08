"""Allow event authorization and storage outcomes in audit logs."""

from alembic import op
from sqlalchemy import text


revision = "a909e501"
down_revision = "d9f3a1b2e405"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.audit_logs "
        "DROP CONSTRAINT IF EXISTS audit_logs_outcome_valid"
    )
    op.execute(
        "ALTER TABLE public.audit_logs "
        "ADD CONSTRAINT audit_logs_outcome_valid "
        "CHECK (outcome IN "
        "('success', 'failure', 'denied', 'conflict', 'unavailable'))"
    )


def downgrade() -> None:
    has_new_outcomes = op.get_bind().execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM public.audit_logs "
            "WHERE outcome NOT IN ('success', 'failure'))"
        )
    ).scalar_one()
    if has_new_outcomes:
        raise RuntimeError(
            "No se puede revertir el esquema: audit_logs ya contiene "
            "resultados de eventos de M09."
        )
    op.execute(
        "ALTER TABLE public.audit_logs "
        "DROP CONSTRAINT IF EXISTS audit_logs_outcome_valid"
    )
    op.execute(
        "ALTER TABLE public.audit_logs "
        "ADD CONSTRAINT audit_logs_outcome_valid "
        "CHECK (outcome IN ('success', 'failure'))"
    )
