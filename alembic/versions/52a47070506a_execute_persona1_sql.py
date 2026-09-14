"""execute_persona1_sql

Revision ID: 52a47070506a
Revises: 
Create Date: 2026-09-06 23:36:20.195614

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import os


# revision identifiers, used by Alembic.
revision: str = '52a47070506a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Leer y ejecutar el SQL crudo de Persona 1
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    
    with open(os.path.join(base_dir, 'db', 'migrations', '001_create_games_and_metrics.sql'), 'r') as f:
        create_sql = f.read()
        op.execute(sa.text(create_sql))
        
    with open(os.path.join(base_dir, 'db', 'seed', '001_seed_games_and_metrics.sql'), 'r') as f:
        seed_sql = f.read()
        op.execute(sa.text(seed_sql))


def downgrade() -> None:
    op.drop_table('game_metrics')
    op.drop_table('games')
