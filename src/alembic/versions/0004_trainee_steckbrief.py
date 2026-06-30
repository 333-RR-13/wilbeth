"""Trainee.steckbrief-Spalte ergaenzen

Revision ID: 0004steckbrief
Revises: 0003kategorie
Create Date: 2026-06-30 00:00:00.000000

Aenderungen:
- Neue nullable Text-Spalte trainee.steckbrief (frei editierbarer Steckbrief).

Postgres-safe: nur eine neue nullable Spalte (kein Table-Rewrite).
SQLite: batch_alter_table (render_as_batch=True).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0004steckbrief'
down_revision: Union[str, Sequence[str], None] = '0003kategorie'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('trainee', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('steckbrief', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('trainee', schema=None) as batch_op:
        batch_op.drop_column('steckbrief')
