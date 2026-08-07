"""Department.info_link ergaenzen (Link auf der Abteilungs-Infoseite)

Revision ID: 0015infolink
Revises: 0014notizen
Create Date: 2026-08-07 00:00:00.000000

Aenderungen:
- Neue nullable Text-Spalte department.info_link -- prominenter externer
  Link auf der neuen Abteilungs-Detailseite (z. B. Confluence), Default ""
  auf Anwendungsseite (SQLModel Field-Default, siehe
  app/models/department.py). Nur http/https wird beim Speichern akzeptiert
  (app/utils/text.is_safe_http_url, geprueft in app/routers/departments.py
  bzw. app/routers/ausbilder.py -- ungueltiges Schema ergibt dort 400).

Keine Datenuebernahme noetig: das Feld ist rein additiv (Bestandsabteilungen
haben schlicht keinen Link, NULL wird von der Anwendungsschicht wie ""
behandelt, analog dept.info_text seit 0005abteilunginfo).

Postgres-safe: nur eine neue nullable Text-Spalte, kein server_default, kein
Table-Rewrite -- analog 0005/0007/0012/0013. SQLite: batch_alter_table
(render_as_batch=True).

downgrade() entfernt die Spalte ersatzlos (Ruecklauf im Ernstfall ist die
Datensicherung vor dem Upgrade).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0015infolink'
down_revision: Union[str, Sequence[str], None] = '0014notizen'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('info_link', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.drop_column('info_link')
