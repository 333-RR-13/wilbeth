"""Trainee.upn ergaenzen (Entra UserPrincipalName fuer SSO-Matching)

Revision ID: 0008upn
Revises: 0007bestaetigung
Create Date: 2026-07-15 00:00:00.000000

Aenderungen:
- Neue nullable Text-Spalte trainee.upn (Entra UserPrincipalName), genutzt um
  einen eingeloggten SSO-User via resolve_role() auf einen aktiven Trainee zu
  matchen (case-insensitive Vergleich).

Postgres-safe: nur eine neue nullable Text-Spalte (kein Boolean, kein
server_default, kein Table-Rewrite) – analog info_text/steckbrief.
SQLite: batch_alter_table (render_as_batch=True).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0008upn'
down_revision: Union[str, Sequence[str], None] = '0007bestaetigung'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('trainee', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('upn', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('trainee', schema=None) as batch_op:
        batch_op.drop_column('upn')
