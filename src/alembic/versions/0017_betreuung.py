"""Betreuer-Tabellen (Personen, die einen Azubi/Studi ueber die gesamte
Ausbildung begleiten, mit Beruf-Zustaendigkeit + Ausnahmen)

Revision ID: 0017betreuung
Revises: 0016berufe
Create Date: 2026-08-12 00:00:00.000000

Aenderungen:
- Neue Tabelle betreuer: id, upn (unique/index), name, funktion, email,
  telefon, notiz, aktiv, berufe (JSON-Liste von Beruf-Tokens, LEER = alle
  Berufe). Siehe app/models/betreuer.py fuer die fachliche Beschreibung
  (Regel + Ausnahmen).
- Neue Tabelle betreuer_trainee: id, betreuer_id (FK->betreuer.id, CASCADE),
  trainee_id (FK->trainee.id, CASCADE), modus ("ZUSAETZLICH"|"AUSGENOMMEN"),
  mit UniqueConstraint(betreuer_id, trainee_id) -- pro Paar darf es nur EINE
  Ausnahme geben.
- Datenuebernahme (einmalig): fuer jede UPN, die aktuell in irgendeiner
  Department.verantwortliche-Zeichenkette steht (Trennzeichen Komma/
  Semikolon/Newline, identische Logik zu
  app.services.verantwortliche_utils.parse_verantwortliche, hier als eigene
  migrations-lokale Kopie ohne app/-Import, analog 0016berufe), wird GENAU
  EIN betreuer-Datensatz angelegt (funktion="TECHNISCH", berufe=[], name="")
  -- dieselbe UPN in mehreren Abteilungen erzeugt KEINE Dublette (case-
  insensitiver Vergleich; die zuerst gefundene Schreibweise gewinnt).
  Department.verantwortliche selbst bleibt unangetastet (die Abteilungs-
  Zustaendigkeit -- app.services.auth_service.allowed_dept_ids -- liest
  weiterhin ausschliesslich dieses Feld, nicht die neue betreuer-Tabelle).
  Dialekt-neutral (reines SQLAlchemy-Core), im Offline-Modus
  (context.is_offline_mode()) uebersprungen -- analog 0012/0013/0014/0016.

Postgres-safe: zwei neue Tabellen, keine Aenderung an Bestandstabellen (kein
Table-Rewrite). Text-/JSON-Spalten sind nullable=True OHNE server_default
(Anwendungsseite liefert die Default-Werte beim Anlegen, analog
0011/0012/0016) -- NIEMALS server_default=sa.text('0') (SQLite-spezifische
Syntax, auf Postgres ein Typfehler). Die einzige Boolean-Spalte (aktiv) ist
NOT NULL mit server_default=sa.true() (analog 0001/0006/0011 -- fuer eine
neue, leere Tabelle unproblematisch, kein Rewrite-Risiko).

downgrade() droppt beide Tabellen ersatzlos (die Betreuer-Zuordnung geht
verloren -- Department.verantwortliche/allowed_dept_ids sind davon NICHT
betroffen, da sie unabhaengig von dieser Tabelle funktionieren). Ruecklauf
im Ernstfall ist die Datensicherung vor dem Upgrade.
"""
import re
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0017betreuung'
down_revision: Union[str, Sequence[str], None] = '0016berufe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'betreuer',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('upn', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('funktion', sa.Text(), nullable=True),
        sa.Column('email', sa.Text(), nullable=True),
        sa.Column('telefon', sa.Text(), nullable=True),
        sa.Column('notiz', sa.Text(), nullable=True),
        sa.Column('aktiv', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('berufe', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_betreuer_upn'), 'betreuer', ['upn'], unique=True)

    op.create_table(
        'betreuer_trainee',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('betreuer_id', sa.Integer(), nullable=False),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('modus', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['betreuer_id'], ['betreuer.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('betreuer_id', 'trainee_id', name='uq_betreuer_trainee'),
    )
    op.create_index(
        op.f('ix_betreuer_trainee_betreuer_id'), 'betreuer_trainee', ['betreuer_id'], unique=False
    )
    op.create_index(
        op.f('ix_betreuer_trainee_trainee_id'), 'betreuer_trainee', ['trainee_id'], unique=False
    )

    _uebernehme_verantwortliche_als_betreuer()


# Trennzeichen-Regex identisch zu
# app.services.verantwortliche_utils.parse_verantwortliche -- hier als eigene
# migrations-lokale Kopie ohne app/-Import (analog 0016berufe).
_TRENNER_RE = re.compile(r"[,;\n]")


def _parse_verantwortliche(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [teil.strip() for teil in _TRENNER_RE.split(raw) if teil.strip()]


def _uebernehme_verantwortliche_als_betreuer() -> None:
    """Legt fuer jede (case-insensitiv distinkte) UPN aus
    Department.verantwortliche einen betreuer-Datensatz an (funktion=
    "TECHNISCH", berufe=[], name="") -- keine Dubletten, auch nicht wenn
    dieselbe UPN in mehreren Abteilungen steht.

    Dialekt-neutral (SQLite + PostgreSQL): reines SQLAlchemy-Core. Im
    Offline-Modus (alembic --sql) gibt es keine Verbindung, von der Zeilen
    gelesen werden koennten -- die Datenuebernahme wird dann uebersprungen,
    analog 0012/0013/0014/0016.
    """
    if context.is_offline_mode():
        return

    bind = op.get_bind()

    rows = bind.execute(sa.text("SELECT verantwortliche FROM department")).fetchall()

    # Erstes Vorkommen gewinnt die Schreibweise; Dedup ueber die
    # kleingeschriebene Form (analog verantwortliche_utils.people_by_upn).
    gesehen: set[str] = set()
    neue_upns: list[str] = []
    for (verantwortliche,) in rows:
        for eintrag in _parse_verantwortliche(verantwortliche):
            key = eintrag.lower()
            if key not in gesehen:
                gesehen.add(key)
                neue_upns.append(eintrag)

    if not neue_upns:
        return

    # Bereits vorhandene betreuer-UPNs (defensiv -- die Tabelle ist zu diesem
    # Zeitpunkt normalerweise leer, aber ein doppelter Migrationslauf o.ae.
    # soll trotzdem keine Dubletten erzeugen).
    bestehende = {
        upn.lower() for (upn,) in bind.execute(sa.text("SELECT upn FROM betreuer")).fetchall()
    }

    insert_stmt = sa.text(
        "INSERT INTO betreuer (upn, name, funktion, email, telefon, notiz, aktiv, berufe) "
        "VALUES (:upn, '', 'TECHNISCH', '', '', '', :aktiv, :berufe)"
    ).bindparams(sa.bindparam("berufe", type_=sa.JSON()))

    for upn in neue_upns:
        if upn.lower() in bestehende:
            continue
        bind.execute(insert_stmt, {"upn": upn, "aktiv": True, "berufe": []})
        bestehende.add(upn.lower())


def downgrade() -> None:
    op.drop_index(op.f('ix_betreuer_trainee_trainee_id'), table_name='betreuer_trainee')
    op.drop_index(op.f('ix_betreuer_trainee_betreuer_id'), table_name='betreuer_trainee')
    op.drop_table('betreuer_trainee')

    op.drop_index(op.f('ix_betreuer_upn'), table_name='betreuer')
    op.drop_table('betreuer')
