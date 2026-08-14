"""Betreuer.funktionen: eine Person kann MEHRERE Funktionen haben

Revision ID: 0018funktionen
Revises: 0017betreuung
Create Date: 2026-08-14 00:00:00.000000

Aenderungen:
- Neue nullable JSON-Spalte betreuer.funktionen (Liste von Funktion-Tokens,
  z. B. ["HR", "TECHNISCH"]), Default [] auf Anwendungsseite (SQLModel
  Field-Default, siehe app/models/betreuer.py). Ersetzt fachlich die
  Einzelwert-Spalte funktion (Mehrfachauswahl -- dieselbe Person kann z. B.
  gleichzeitig fachlicher Ausbilder UND HR-Ausbilderin sein) -- die Spalte
  funktion bleibt unangetastet in der DB stehen (Datensicherung/
  Ruckwaertskompatibilitaet, analog Department.zielgruppe seit Migration
  0016berufe), wird aber ab dieser Aenderung nicht mehr in der UI oder der
  Sortierung (app/services/betreuung_utils.py) ausgewertet.
- Datenuebernahme (einmalig): fuer jeden Bestands-Betreuer wird funktionen
  aus dem bisherigen Einzelwert befuellt -- ein bekannter Funktion-Token
  (HR/TECHNISCH/EINSATZPLANUNG/SONSTIGES) wird zur Einzelliste [funktion];
  ein leerer oder unbekannter Wert wird zu einer leeren Liste (KEIN Fallback
  auf SONSTIGES -- eine leere Funktionsliste ist ausdruecklich erlaubt, s.
  app/models/betreuer.py). Dialekt-neutral (reines SQLAlchemy-Core), im
  Offline-Modus (context.is_offline_mode()) uebersprungen, analog
  0012/0013/0014/0016/0017.

Postgres-safe: eine neue nullable JSON-Spalte ohne server_default, kein
Table-Rewrite -- analog 0012/0013/0016/0017. SQLite: batch_alter_table
(render_as_batch=True).

downgrade() entfernt die Spalte funktionen ersatzlos (die Mehrfachauswahl
geht verloren -- die Einzelwert-Spalte funktion bleibt davon unberuehrt, da
sie unabhaengig von dieser Spalte weiter in der DB steht). Ruecklauf im
Ernstfall ist die Datensicherung vor dem Upgrade.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0018funktionen'
down_revision: Union[str, Sequence[str], None] = '0017betreuung'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Bekannte Funktion-Tokens (identisch zu FUNKTION_LABELS.keys() in
# app/models/betreuer.py, hier als eigene migrations-lokale Kopie ohne
# app/-Import, analog 0016berufe/0017betreuung).
_BEKANNTE_FUNKTIONEN = {"HR", "TECHNISCH", "EINSATZPLANUNG", "SONSTIGES"}


def upgrade() -> None:
    with op.batch_alter_table('betreuer', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('funktionen', sa.JSON(), nullable=True)
        )

    _uebernehme_funktion_als_funktionen()


def _funktionen_aus_einzelwert(funktion: str | None) -> list[str]:
    """Leitet die neue funktionen-Liste aus dem bisherigen Einzelwert ab
    (reine Funktion, keine Alembic-/DB-Abhaengigkeit -- direkt unit-testbar,
    analog 0016berufe: _art_aus_klassenname).

    >>> _funktionen_aus_einzelwert("TECHNISCH")
    ['TECHNISCH']
    >>> _funktionen_aus_einzelwert("")
    []
    >>> _funktionen_aus_einzelwert(None)
    []
    >>> _funktionen_aus_einzelwert("UNBEKANNT")
    []
    """
    return [funktion] if funktion in _BEKANNTE_FUNKTIONEN else []


def _uebernehme_funktion_als_funktionen() -> None:
    """Einmalige Datenuebernahme: funktionen je Bestands-Betreuer aus dem
    bisherigen Einzelwert funktion ableiten (siehe Modul-Docstring bzw.
    _funktionen_aus_einzelwert oben).

    Dialekt-neutral (SQLite + PostgreSQL): reines SQLAlchemy-Core. Im
    Offline-Modus (alembic --sql) gibt es keine Verbindung, von der Zeilen
    gelesen werden koennten -- die Datenuebernahme wird dann uebersprungen,
    analog 0012/0013/0014/0016/0017.
    """
    if context.is_offline_mode():
        return

    bind = op.get_bind()

    rows = bind.execute(sa.text("SELECT id, funktion FROM betreuer")).fetchall()

    update_stmt = sa.text(
        "UPDATE betreuer SET funktionen = :funktionen WHERE id = :id"
    ).bindparams(sa.bindparam("funktionen", type_=sa.JSON()))

    for betreuer_id, funktion in rows:
        bind.execute(
            update_stmt,
            {"funktionen": _funktionen_aus_einzelwert(funktion), "id": betreuer_id},
        )


def downgrade() -> None:
    with op.batch_alter_table('betreuer', schema=None) as batch_op:
        batch_op.drop_column('funktionen')
