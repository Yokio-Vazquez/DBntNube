"""Create the M02 relational model."""

from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "b7c2d9e4f1a0"
down_revision = "52a47070506a"
branch_labels = None
depends_on = None


def _sql_file(name: str) -> str:
    project_root = Path(__file__).resolve().parents[2]
    return (project_root / "db" / "migrations" / name).read_text(encoding="utf-8")


def upgrade() -> None:
    op.execute(sa.text(_sql_file("002_create_relational_model.sql")))
    op.execute(sa.text(_sql_file("002_seed_relational_model.sql")))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE game_metrics "
        "DROP CONSTRAINT IF EXISTS game_metrics_metric_definition_fk"
    ))
    op.execute(sa.text("DROP TABLE IF EXISTS game_platforms"))
    op.execute(sa.text("DROP TABLE IF EXISTS platforms"))
    op.execute(sa.text("DROP TABLE IF EXISTS metric_definitions"))