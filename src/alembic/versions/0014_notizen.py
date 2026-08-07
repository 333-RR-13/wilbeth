"""trainee_notiz-Tabelle (chronologischer Notiz-Verlauf ueber einen Trainee)

Revision ID: 0014notizen
Revises: 0013bereich
Create Date: 2026-08-07 00:00:00.000000

Aenderungen:
- Neue Tabelle trainee_notiz: chronologischer Notiz-Verlauf eines Ausbilders
  ueber einen Trainee (mehrere Eintraege moeglich), getrennt vom bestehenden
  Assignment.notiz/Assignment.feedback (Notiz/Feedback ZUM EINSATZ, bleibt
  unangetastet) und vom bisherigen einzelnen Freitextfeld Trainee.notizen.
  Eine Notiz entsteht entweder direkt im Profil (department_id/kw_* = NULL)
  oder aus einem Einsatz-Block heraus (department_id + KW-Zeitraum als
  Kontext). Der Azubi sieht diese Notizen nie (siehe app/routers/share.py).
- Datenuebernahme (einmalig): fuer jeden Trainee mit nicht-leerem (nach
  .strip()) Trainee.notizen-Feld wird GENAU EIN trainee_notiz-Eintrag
  angelegt (text = der bisherige Notizen-Text, verfasser_upn='',
  verfasser_name='uebernommen aus Stammdaten', erstellt_am=heutiges Datum,
  department_id/kw_* = NULL). Die Spalte trainee.notizen bleibt in der DB
  unveraendert bestehen (kein Drop -- Datensicherung/Rueckwaertskompatibilitaet).
  Dialekt-neutral (reines SQLAlchemy-Core), im Offline-Modus (alembic --sql)
  uebersprungen, analog 0012/0013.

Postgres-safe: neue Tabelle, keine Aenderung an Bestandstabellen. Alle
Textspalten (text, verfasser_upn, verfasser_name) sind sa.Text(),
nullable=True OHNE server_default -- auch 'text', obwohl im SQLModel-Feld
ein Pflichtfeld ohne Default (Praezedenzfall: Abwesenheit.typ in 0012 ist
ebenfalls ein Pflichtfeld im Modell, aber nullable=True in der Migration,
weil die Anwendungsschicht den Wert beim Anlegen liefert). id/trainee_id
sind NOT NULL (strukturell, analog abwesenheit.trainee_id in 0012).
Fremdschluessel: trainee_id -> trainee.id mit ondelete='CASCADE' + Index
(analog abwesenheit), department_id -> department.id mit ondelete='SET NULL'
(kein Index noetig). kw_von/jahr_von/kw_bis/jahr_bis sind sa.Integer(),
erstellt_am ist sa.Date(), alle nullable=True.

downgrade() droppt nur die neue Tabelle trainee_notiz (Datenverlust der
uebernommenen Notizen im Ruecklauf akzeptiert, analog 0012/0013 -- der
Ruecklauf im Ernstfall ist die Datensicherung vor dem Upgrade). Die Spalte
trainee.notizen wird von downgrade() nicht angefasst.
"""
from datetime import date
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0014notizen'
down_revision: Union[str, Sequence[str], None] = '0013bereich'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'trainee_notiz',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('verfasser_upn', sa.Text(), nullable=True),
        sa.Column('verfasser_name', sa.Text(), nullable=True),
        sa.Column('erstellt_am', sa.Date(), nullable=True),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('kw_von', sa.Integer(), nullable=True),
        sa.Column('jahr_von', sa.Integer(), nullable=True),
        sa.Column('kw_bis', sa.Integer(), nullable=True),
        sa.Column('jahr_bis', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['department_id'], ['department.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_trainee_notiz_trainee_id'), 'trainee_notiz', ['trainee_id'], unique=False
    )

    _uebernehme_bestands_notizen()


def _uebernehme_bestands_notizen() -> None:
    """Einmalige Datenuebernahme: je Trainee mit nicht-leerem (nach .strip())
    notizen-Feld genau einen trainee_notiz-Eintrag anlegen.

    Dialekt-neutral (SQLite + PostgreSQL): reines SQLAlchemy-Core. Im
    Offline-Modus (alembic --sql) gibt es keine Verbindung, von der Zeilen
    gelesen werden koennten -- die Datenuebernahme wird dann uebersprungen
    (nur die Tabellen-DDL wird ausgegeben), analog zu 0012/0013.
    """
    if context.is_offline_mode():
        return

    bind = op.get_bind()
    today = date.today()

    rows = bind.execute(sa.text("SELECT id, notizen FROM trainee")).fetchall()
    insert_stmt = sa.text(
        "INSERT INTO trainee_notiz "
        "(trainee_id, text, verfasser_upn, verfasser_name, erstellt_am, "
        "department_id, kw_von, jahr_von, kw_bis, jahr_bis) "
        "VALUES (:trainee_id, :text, '', 'uebernommen aus Stammdaten', :erstellt_am, "
        "NULL, NULL, NULL, NULL, NULL)"
    )
    for trainee_id, notizen in rows:
        if notizen is None or not notizen.strip():
            continue
        bind.execute(
            insert_stmt,
            {"trainee_id": trainee_id, "text": notizen, "erstellt_am": today},
        )


def downgrade() -> None:
    op.drop_index(op.f('ix_trainee_notiz_trainee_id'), table_name='trainee_notiz')
    op.drop_table('trainee_notiz')
