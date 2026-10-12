"""create v_operational_summary view for cdrl_operator

Revision ID: d9f3a1b2e405
Revises: c84f39d2a611
Create Date: 2026-10-12 02:00:00.000000

Crea la vista de lectura v_operational_summary (owner: cdrl_migrator)
y concede SELECT a cdrl_operator para que pueda monitorear el sistema
sin acceder directamente a las tablas de negocio.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d9f3a1b2e405"
down_revision = "c84f39d2a611"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW public.v_operational_summary AS
        SELECT
            g.id            AS game_id,
            g.title         AS game_title,
            COUNT(gm.id)    AS total_metrics,
            MAX(gm.measured_at) AS last_measured_at,
            SUM(CASE WHEN gm.deleted_at IS NULL THEN 0 ELSE 1 END)
                            AS soft_deleted_count
        FROM public.games g
        LEFT JOIN public.game_metrics gm ON gm.game_id = g.id
        GROUP BY g.id, g.title
        ORDER BY g.id
    """)
    op.execute("ALTER VIEW public.v_operational_summary OWNER TO cdrl_migrator")
    op.execute("GRANT SELECT ON public.v_operational_summary TO cdrl_operator")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public.v_operational_summary FROM cdrl_operator")
    op.execute("DROP VIEW IF EXISTS public.v_operational_summary")
