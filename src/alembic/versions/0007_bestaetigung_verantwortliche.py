"""Assignment.bestaetigung und Department.verantwortliche ergaenzen

Revision ID: 0007bestaetigung
Revises: 0006archiviert
Create Date: 2026-07-02 00:00:00.000000

Aenderungen:
- Neue nullable Text-Spalte assignment.bestaetigung (Bestaetigungsstatus einer
  Abteilungs-Einsatzzelle: "offen" | "bestaetigt" | "abgelehnt").
- Neue nullable Text-Spalte department.verantwortliche (verantwortliche
  Ausbilder als UPNs/E-Mails, kommasepariert).

Postgres-safe: nur neue nullable Text-Spalten (kein Boolean, kein
server_default, kein Table-Rewrite) – analog info_text/steckbrief.
SQLite: batch_alter_table (render_as_batch=True).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0007bestaetigung'
down_revision: Union[str, Sequence[str], None] = '0006archiviert'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assignment', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('bestaetigung', sa.Text(), nullable=True)
        )

    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('verantwortliche', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('assignment', schema=None) as batch_op:
        batch_op.drop_column('bestaetigung')

    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.drop_column('verantwortliche')
