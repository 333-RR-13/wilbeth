"""schoolyear.archiviert ergaenzen + Best-Effort-Anker-Backfill

Revision ID: 0006archiviert
Revises: 0005abteilunginfo
Create Date: 2026-06-30 00:00:00.000000

Aenderungen:
- Neue NOT NULL Boolean-Spalte schoolyear.archiviert (default False/0).
- Best-Effort-Backfill: Trainees ohne ausbildungsbeginn, die aber Memberships
  haben, erhalten das fruehste Membership-Jahr als Anker-Startdatum
  (1. September des start_year) und klasse_id aus der Einstiegsklasse.

SQLite: batch_alter_table (render_as_batch=True).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0006archiviert'
down_revision: Union[str, Sequence[str], None] = '0005abteilunginfo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Neue Spalte schoolyear.archiviert
    with op.batch_alter_table('schoolyear', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'archiviert',
                sa.Boolean(),
                nullable=False,
                # sa.false() rendert dialekt-korrekt (PostgreSQL: false, SQLite: 0).
                # sa.text('0') wuerde auf PostgreSQL scheitern (boolean != integer).
                server_default=sa.false(),
            )
        )

    # 2. Best-Effort-Anker-Backfill
    #    Fuer Trainees ohne ausbildungsbeginn aber mit Memberships:
    #    - fruehstes Membership-Jahr (via schoolyear.start_year) ermitteln
    #    - ausbildungsbeginn auf 1. September des start_year setzen
    #    - klasse_id auf die Klasse des fruehesten Membership-Jahres setzen
    try:
        bind = op.get_bind()

        # Alle Trainees ohne ausbildungsbeginn die mindestens eine Membership haben
        rows = bind.execute(sa.text("""
            SELECT DISTINCT t.id
            FROM trainee t
            JOIN trainee_class_membership m ON m.trainee_id = t.id
            WHERE t.ausbildungsbeginn IS NULL
        """)).fetchall()

        for (trainee_id,) in rows:
            try:
                # Fruehstes Membership nach schoolyear.start_year
                earliest = bind.execute(sa.text("""
                    SELECT m.klasse_id, sy.start_year
                    FROM trainee_class_membership m
                    JOIN schoolyear sy ON sy.id = m.schoolyear_id
                    WHERE m.trainee_id = :tid
                    ORDER BY sy.start_year ASC
                    LIMIT 1
                """), {"tid": trainee_id}).fetchone()

                if earliest is None:
                    continue

                klasse_id, start_year = earliest

                # ausbildungsbeginn = 1. September des start_year
                ausbildungsbeginn = f"{start_year}-09-01"

                bind.execute(sa.text("""
                    UPDATE trainee
                    SET ausbildungsbeginn = :ab, klasse_id = :kid
                    WHERE id = :tid
                      AND ausbildungsbeginn IS NULL
                """), {"ab": ausbildungsbeginn, "kid": klasse_id, "tid": trainee_id})

            except Exception:
                # Defensiv: Fehler fuer einzelnen Trainee tolerieren
                continue

    except Exception:
        # Backfill ist Best-Effort – Migration soll trotzdem durchlaufen
        pass


def downgrade() -> None:
    with op.batch_alter_table('schoolyear', schema=None) as batch_op:
        batch_op.drop_column('archiviert')
