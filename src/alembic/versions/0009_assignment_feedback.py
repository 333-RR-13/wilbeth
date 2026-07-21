"""Assignment.feedback ergaenzen (Ausbilder-Feedback zum Einsatz)

Revision ID: 0009feedback
Revises: 0008upn
Create Date: 2026-07-21 00:00:00.000000

Aenderungen:
- Neue nullable Text-Spalte assignment.feedback (Ausbilder-Feedback zu einem
  einzelnen Einsatz).

Postgres-safe: nur eine neue nullable Text-Spalte (kein Boolean, kein
server_default, kein Table-Rewrite) – analog info_text/steckbrief.
SQLite: batch_alter_table (render_as_batch=True).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0009feedback'
down_revision: Union[str, Sequence[str], None] = '0008upn'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assignment', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('feedback', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('assignment', schema=None) as batch_op:
        batch_op.drop_column('feedback')
