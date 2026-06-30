"""Abteilung info_text und Trainee ausbildungsbeginn ergaenzen

Revision ID: 0005abteilunginfo
Revises: 0004steckbrief
Create Date: 2026-06-30 00:00:00.000000

Aenderungen:
- Neue nullable Date-Spalte trainee.ausbildungsbeginn (Beginn der Ausbildung/des Studiums).
- Neue nullable Text-Spalte department.info_text (Beschreibungs-/Infotext der Abteilung).

Postgres-safe: nur neue nullable Spalten (kein Table-Rewrite).
SQLite: batch_alter_table (render_as_batch=True).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0005abteilunginfo'
down_revision: Union[str, Sequence[str], None] = '0004steckbrief'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('trainee', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('ausbildungsbeginn', sa.Date(), nullable=True)
        )

    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('info_text', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('trainee', schema=None) as batch_op:
        batch_op.drop_column('ausbildungsbeginn')

    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.drop_column('info_text')
