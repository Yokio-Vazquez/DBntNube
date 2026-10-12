"""Add append-only audit log and logical metric deletion."""

from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "c84f39d2a611"
down_revision = "b7c2d9e4f1a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    project_root = Path(__file__).resolve().parents[2]
    sql = (project_root / "db" / "migrations" / "004_audit_and_soft_delete.sql").read_text(encoding="utf-8")
    op.execute(sa.text(sql))


def downgrade() -> None:
    op.execute(sa.text("DROP FUNCTION IF EXISTS soft_delete_metric(BIGINT)"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS reject_audit_log_mutation()"))
    op.execute(sa.text("DROP TABLE IF EXISTS audit_logs"))
    op.execute(sa.text("ALTER TABLE game_metrics DROP COLUMN IF EXISTS deleted_at"))