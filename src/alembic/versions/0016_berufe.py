"""TraineeClass.art und Department.erlaubte_berufe ergaenzen (Ausbildung/
Studium je Klasse, praezise Beruf-Zulassung je Abteilung)

Revision ID: 0016berufe
Revises: 0015infolink
Create Date: 2026-08-12 00:00:00.000000

Aenderungen:
- Neue nullable Text-Spalte trainee_class.art ("AUSBILDUNG" | "STUDIUM"),
  Default "AUSBILDUNG" auf Anwendungsseite (SQLModel Field-Default, siehe
  app/models/trainee_class.py). Sagt, ob eine Klasse einen Ausbildungsberuf
  (FISI/FIAE, Buerokaufleute, ...) oder einen dualen Studiengang (DH-Kohorte)
  fuehrt. Steuert im Trainee-Formular die Beruf-Auswahl je Rolle (TEIL A,
  siehe app/routers/trainees.py).
- Neue nullable JSON-Spalte department.erlaubte_berufe (Liste von
  Beruf-Tokens, z. B. ["FISI", "FIAE"]), Default [] auf Anwendungsseite
  (SQLModel Field-Default, siehe app/models/department.py). LEERE Liste
  bedeutet ausdruecklich "alle Berufe erlaubt" (bisheriger Zustand "BEIDE").
  Ersetzt fachlich department.zielgruppe fuer die Bereichs-Konfliktpruefung
  (TEIL B) -- die Spalte zielgruppe bleibt unangetastet in der DB stehen
  (Datensicherung/Ruckwaertskompatibilitaet, siehe Kommentar in
  app/models/department.py), wird aber ab dieser Aenderung nicht mehr in der
  UI oder der Konfliktpruefung ausgewertet.
- Datenuebernahme (einmalig):
  * trainee_class.art wird aus dem Klassennamen abgeleitet: Namen MIT
    Lehrjahr-Muster ("n. LJ", z. B. "FISI 2. LJ") werden "AUSBILDUNG";
    Namen OHNE (die DH-Kohorten, z. B. "DHBW Digital Business Management")
    werden "STUDIUM". Dieselbe Erkennung wie
    membership_utils.beruf_und_lehrjahr, hier aber als eigene reine Funktion
    OHNE Import aus app/ (direkt unit-testbar, keine Alembic-/DB-
    Abhaengigkeit), analog 0013.
  * department.erlaubte_berufe wird aus der bisherigen zielgruppe UND den
    (bereits durch Migration 0013 befuellten) trainee_class.bereich-Werten
    abgeleitet: zielgruppe="IT" -> alle Beruf-Tokens, deren Klassen
    bereich="IT" haben; zielgruppe="KAUFMAENNISCH" -> analog mit bereich=
    "KAUFMAENNISCH"; zielgruppe="BEIDE" -> leere Liste (= alle erlaubt,
    unveraendertes Verhalten). Der Beruf-Token wird aus dem Klassennamen
    abgeleitet (LJ-Muster -> Praefix vor "n. LJ", sonst der volle
    Klassenname -- identische Logik zu
    membership_utils.beruf_und_lehrjahr/beruf_optionen, hier ebenfalls als
    eigene reine Funktion ohne app/-Import).
  Dialekt-neutral (reines SQLAlchemy-Core), im Offline-Modus (alembic --sql)
  uebersprungen (nur die Spalten-DDL wird ausgegeben), analog 0012/0013/0014.

Postgres-safe: zwei neue nullable Spalten (Text bzw. JSON) ohne
server_default, kein Table-Rewrite -- analog 0007/0012/0013/0015. SQLite:
batch_alter_table (render_as_batch=True). Die JSON-Spalte wird ueber
sa.JSON() dialektneutral erzeugt (Postgres: json, SQLite: als TEXT emuliert)
und beim Befuellen ueber einen typisierten bindparam gesetzt, damit
SQLAlchemy pro Dialekt korrekt (de-)serialisiert.

downgrade() entfernt beide neuen Spalten ersatzlos (die Klassifizierung geht
verloren -- Ruecklauf im Ernstfall ist die Datensicherung vor dem Upgrade).
Die Spalte department.zielgruppe wird von dieser Migration nicht angefasst.
"""
import re
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0016berufe'
down_revision: Union[str, Sequence[str], None] = '0015infolink'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Klassennamen folgen der Konvention "<Beruf> <n>. LJ" (z. B. "FISI 2. LJ") --
# dieselbe Konvention wie membership_utils._LJ_RE, hier als eigene
# Migrations-lokale Kopie ohne app/-Import.
_LJ_RE = re.compile(r"^(?P<beruf>.+?)\s*(?P<lj>\d)\.\s*LJ\s*$")


def upgrade() -> None:
    with op.batch_alter_table('trainee_class', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('art', sa.Text(), nullable=True)
        )

    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('erlaubte_berufe', sa.JSON(), nullable=True)
        )

    _klassifiziere_bestandsdaten()


def _art_aus_klassenname(name: str | None) -> str:
    """Leitet die Art des Bildungswegs aus dem Klassennamen ab (reine
    Funktion, keine Alembic-/DB-Abhaengigkeit -- direkt unit-testbar).

    Klassen MIT Lehrjahr-Muster ("n. LJ") sind Ausbildungsberufe; Klassen
    OHNE (die DH-Kohorten, die stattdessen in Semestern zaehlen) sind duale
    Studiengaenge.

    >>> _art_aus_klassenname("FISI 2. LJ")
    'AUSBILDUNG'
    >>> _art_aus_klassenname("Bürokaufleute 1. LJ")
    'AUSBILDUNG'
    >>> _art_aus_klassenname("DHBW Digital Business Management")
    'STUDIUM'
    >>> _art_aus_klassenname(None)
    'AUSBILDUNG'
    """
    if not name:
        return "AUSBILDUNG"
    return "AUSBILDUNG" if _LJ_RE.match(name) else "STUDIUM"


def _beruf_token_aus_klassenname(name: str | None) -> str:
    """Leitet den Beruf-Token aus dem Klassennamen ab (reine Funktion,
    identische Logik zu membership_utils.beruf_und_lehrjahr, hier ohne
    app/-Import).

    >>> _beruf_token_aus_klassenname("FISI 2. LJ")
    'FISI'
    >>> _beruf_token_aus_klassenname("DHBW Digital Business Management")
    'DHBW Digital Business Management'
    >>> _beruf_token_aus_klassenname(None)
    ''
    """
    if not name:
        return ""
    m = _LJ_RE.match(name)
    if m:
        return m.group("beruf").strip()
    return name.strip()


def _klassifiziere_bestandsdaten() -> None:
    """Einmalige Datenuebernahme: trainee_class.art je Bestandsklasse aus dem
    Namen ableiten (siehe _art_aus_klassenname); department.erlaubte_berufe
    je Bestandsabteilung aus zielgruppe + trainee_class.bereich ableiten.

    Dialekt-neutral (SQLite + PostgreSQL): reines SQLAlchemy-Core. Im
    Offline-Modus (alembic --sql) gibt es keine Verbindung, von der Zeilen
    gelesen werden koennten -- die Datenuebernahme wird dann uebersprungen,
    analog zu 0012/0013/0014.
    """
    if context.is_offline_mode():
        return

    bind = op.get_bind()

    # trainee_class.art: aus dem Klassennamen abgeleitet
    klassen_rows = bind.execute(sa.text("SELECT id, name, bereich FROM trainee_class")).fetchall()
    for klasse_id, name, _bereich in klassen_rows:
        art = _art_aus_klassenname(name)
        bind.execute(
            sa.text("UPDATE trainee_class SET art = :art WHERE id = :id"),
            {"art": art, "id": klasse_id},
        )

    # department.erlaubte_berufe: aus zielgruppe + trainee_class.bereich
    # abgeleitete Beruf-Tokens je Bereich (Klassenliste s.o. -- bereich stammt
    # aus Migration 0013 und ist zu diesem Zeitpunkt bereits befuellt).
    berufe_it = sorted({
        _beruf_token_aus_klassenname(name)
        for _id, name, bereich in klassen_rows
        if bereich == "IT" and _beruf_token_aus_klassenname(name)
    })
    berufe_kaufmaennisch = sorted({
        _beruf_token_aus_klassenname(name)
        for _id, name, bereich in klassen_rows
        if bereich == "KAUFMAENNISCH" and _beruf_token_aus_klassenname(name)
    })

    update_dept_stmt = sa.text(
        "UPDATE department SET erlaubte_berufe = :berufe WHERE id = :id"
    ).bindparams(sa.bindparam("berufe", type_=sa.JSON()))

    dept_rows = bind.execute(sa.text("SELECT id, zielgruppe FROM department")).fetchall()
    for dept_id, zielgruppe in dept_rows:
        if zielgruppe == "IT":
            berufe = berufe_it
        elif zielgruppe == "KAUFMAENNISCH":
            berufe = berufe_kaufmaennisch
        else:
            berufe = []
        bind.execute(update_dept_stmt, {"berufe": berufe, "id": dept_id})


def downgrade() -> None:
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.drop_column('erlaubte_berufe')

    with op.batch_alter_table('trainee_class', schema=None) as batch_op:
        batch_op.drop_column('art')
