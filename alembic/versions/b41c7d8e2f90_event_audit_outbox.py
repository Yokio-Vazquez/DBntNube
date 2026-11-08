"""Add a durable outbox for event creation audits."""

from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "b41c7d8e2f90"
down_revision = "a909e501"
branch_labels = None
depends_on = None


def upgrade() -> None:
    project_root = Path(__file__).resolve().parents[2]
    sql = (
        project_root / "db" / "migrations" / "005_event_audit_outbox.sql"
    ).read_text(encoding="utf-8")
    op.execute(sa.text(sql))


def downgrade() -> None:
    has_pending_operations = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM public.event_audit_outbox "
            "WHERE status = 'pending')"
        )
    ).scalar_one()
    if has_pending_operations:
        raise RuntimeError(
            "No se puede revertir el outbox mientras haya auditorías pendientes."
        )
    op.execute(
        "DROP TRIGGER IF EXISTS event_audit_outbox_transition "
        "ON public.event_audit_outbox"
    )
    op.execute("DROP TABLE IF EXISTS public.event_audit_outbox")
    op.execute("DROP FUNCTION IF EXISTS public.guard_event_audit_outbox_transition()")
