"""TraineeClass.bereich und Department.zielgruppe ergaenzen (IT/kaufmaennisch)

Revision ID: 0013bereich
Revises: 0012abwesenheit
Create Date: 2026-08-06 00:00:00.000000

Aenderungen:
- Neue nullable Text-Spalte trainee_class.bereich ("IT" | "KAUFMAENNISCH"),
  Default "IT" auf Anwendungsseite (SQLModel Field-Default, siehe
  app/models/trainee_class.py). Sagt, ob eine Klasse IT-Azubis/-Studis
  (FISI/FIAE) oder kaufmaennische Azubis/-Studis (Buerokaufleute, BWL-
  Studiengaenge) enthaelt. Die Klasse kennt den Beruf, dadurch gilt die
  Zuordnung automatisch auch nach dem Aufruecken -- es braucht dafuer kein
  eigenes Feld am Trainee.
- Neue nullable Text-Spalte department.zielgruppe ("IT" | "KAUFMAENNISCH" |
  "BEIDE"), Default "BEIDE" auf Anwendungsseite. Sagt, welche Azubi-Bereiche
  eine Abteilung grundsaetzlich aufnimmt.
- Datenuebernahme (einmalig):
  * trainee_class.bereich wird anhand des Klassennamens abgeleitet -- Namen,
    die mit "FISI" oder "FIAE" beginnen, werden "IT"; alle anderen
    (Buerokaufleute, Digital Business Management, International Business,
    DH-Kohorten, ...) werden "KAUFMAENNISCH".
  * department.zielgruppe wird fuer ALLE Bestandsabteilungen explizit auf
    "BEIDE" gesetzt -- so wird keine bestehende Planung durch die
    Einfuehrung ploetzlich als Bereichs-Konflikt markiert.
  Dialekt-neutral (reines SQLAlchemy-Core, funktioniert auf SQLite und
  PostgreSQL gleichermassen). Im Offline-Modus (alembic --sql, reine
  DDL-Skriptgenerierung ohne echte Verbindung) wird die Datenuebernahme
  uebersprungen (nur die Spalten-DDL wird ausgegeben), analog zu 0012.

Postgres-safe: nur neue nullable Text-Spalten (kein Boolean, kein
server_default, kein Table-Rewrite) -- analog 0007/0012. SQLite:
batch_alter_table (render_as_batch=True).

downgrade() entfernt beide Spalten ersatzlos (die Klassifizierung geht
verloren -- Ruecklauf im Ernstfall ist die Datensicherung vor dem Upgrade).
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0013bereich'
down_revision: Union[str, Sequence[str], None] = '0012abwesenheit'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('trainee_class', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('bereich', sa.Text(), nullable=True)
        )

    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('zielgruppe', sa.Text(), nullable=True)
        )

    _klassifiziere_bestandsdaten()


def _bereich_aus_klassenname(name: str | None) -> str:
    """Leitet den Ausbildungsbereich aus dem Klassennamen ab (reine Funktion,
    keine Alembic-/DB-Abhaengigkeit -- direkt unit-testbar).

    Namen, die mit "FISI"/"FIAE" beginnen ODER ein eindeutig technisches
    Stichwort enthalten (Informatik, Cyber, IT), werden "IT"; alles andere
    (Buerokaufleute, Digital Business Management, International Business, ...)
    wird "KAUFMAENNISCH".

    Das Stichwort-Kriterium ist bewusst dabei: eine reine FISI/FIAE-Praefix-
    Regel wuerde IT-nahe DH-Studiengaenge wie "DHBW Wirtschaftsinformatik"
    oder "DHBW Cybersecurity" faelschlich als kaufmaennisch einordnen. Die
    Einordnung ist ohnehin nur eine einmalige Startbelegung und auf der
    Klassen-Seite jederzeit korrigierbar.

    >>> _bereich_aus_klassenname("FISI 2. LJ")
    'IT'
    >>> _bereich_aus_klassenname("FIAE 1. LJ")
    'IT'
    >>> _bereich_aus_klassenname("DHBW Wirtschaftsinformatik")
    'IT'
    >>> _bereich_aus_klassenname("DHBW Cybersecurity")
    'IT'
    >>> _bereich_aus_klassenname("Bürokaufleute 1. LJ")
    'KAUFMAENNISCH'
    >>> _bereich_aus_klassenname("Digital Business Management")
    'KAUFMAENNISCH'
    >>> _bereich_aus_klassenname("International Business")
    'KAUFMAENNISCH'
    """
    name_upper = (name or "").strip().upper()
    if name_upper.startswith("FISI") or name_upper.startswith("FIAE"):
        return "IT"
    if any(wort in name_upper for wort in ("INFORMATIK", "CYBER")):
        return "IT"
    # "IT" nur als eigenstaendiges Wort, sonst wuerde z. B. "SECURITY" oder
    # "DIGITAL" ueber ein zufaelliges Teilwort greifen.
    if "IT" in name_upper.replace("-", " ").replace("/", " ").split():
        return "IT"
    return "KAUFMAENNISCH"


def _klassifiziere_bestandsdaten() -> None:
    """Einmalige Datenuebernahme: bereich je Bestandsklasse aus dem Namen
    ableiten (siehe _bereich_aus_klassenname), zielgruppe aller
    Bestandsabteilungen auf "BEIDE" setzen.

    Dialekt-neutral (SQLite + PostgreSQL): reines SQLAlchemy-Core. Im
    Offline-Modus (alembic --sql) gibt es keine Verbindung, von der Zeilen
    gelesen werden koennten -- die Datenuebernahme wird dann uebersprungen,
    analog zu 0012.
    """
    if context.is_offline_mode():
        return

    bind = op.get_bind()

    # trainee_class.bereich: Name beginnt mit FISI/FIAE -> IT, sonst KAUFMAENNISCH
    rows = bind.execute(sa.text("SELECT id, name FROM trainee_class")).fetchall()
    for klasse_id, name in rows:
        bereich = _bereich_aus_klassenname(name)
        bind.execute(
            sa.text("UPDATE trainee_class SET bereich = :bereich WHERE id = :id"),
            {"bereich": bereich, "id": klasse_id},
        )

    # department.zielgruppe: alle Bestandsabteilungen bleiben "BEIDE"
    bind.execute(sa.text("UPDATE department SET zielgruppe = 'BEIDE'"))


def downgrade() -> None:
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.drop_column('zielgruppe')

    with op.batch_alter_table('trainee_class', schema=None) as batch_op:
        batch_op.drop_column('bereich')
