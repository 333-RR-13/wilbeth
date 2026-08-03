"""Abwesenheit-Tabelle (tagegenaue Abwesenheiten als Overlay statt Assignment-URLAUB)

Revision ID: 0012abwesenheit
Revises: 0011bogen
Create Date: 2026-07-31 00:00:00.000000

Aenderungen:
- Neue Tabelle abwesenheit: tagegenauer Abwesenheitszeitraum (von_datum..
  bis_datum, beide inklusive) eines Trainees. Ersetzt den bisherigen
  Assignment-Typ URLAUB, der wegen der UniqueConstraint(trainee_id, kw,
  jahr) den kompletten Abteilungs-Einsatz der Woche verdraengt hat --
  Abwesenheit ist nur noch eine Markierung ueber der Matrix und blockiert
  nichts mehr.
- Datenuebernahme: alle bestehenden Assignment-Zeilen mit typ='URLAUB'
  werden je Trainee nach (jahr, kw) sortiert gelesen, in Werktage
  (Montag..Freitag der jeweiligen ISO-Kalenderwoche) umgerechnet und
  unmittelbar aufeinanderfolgende Wochen (naechster Montag == vorheriger
  Freitag + 3 Tage) zu je EINEM Abwesenheit-Eintrag zusammengefasst.
  quelle wird aus assignment.source abgeleitet (SELBST -> SELBST, alles
  andere -> PLANER), typ ist immer URLAUB, kommentar bleibt leer,
  erstellt_am ist das Datum des Migrationslaufs. Danach werden die
  uebernommenen Assignment-Zeilen (typ='URLAUB') geloescht; FREI-Zeilen und
  alle anderen Assignment-Typen bleiben unangetastet.
  Die Datenuebernahme ist dialekt-neutral (reines Python/SQLAlchemy-Core,
  funktioniert auf SQLite und PostgreSQL gleichermassen).
- KW 53: date.fromisocalendar(jahr, kw, 1) schlaegt fehl, wenn kw=53 in einem
  Jahr mit nur 52 ISO-Kalenderwochen liegt (der Importer akzeptierte bislang
  1..53 fuer JEDES Jahr, solche Zeilen koennen also im Bestand existieren).
  Diese Umrechnung ist in try/except gekapselt: eine betroffene Zeile wird
  NICHT migriert, per print gemeldet und vom abschliessenden DELETE
  ausgenommen (bleibt unveraendert als Assignment(typ='URLAUB') bestehen,
  damit keine Daten stillschweigend verloren gehen); alle anderen Zeilen
  werden wie gewohnt migriert und geloescht.
- Fehlzeiten-Umrechnung Wochen -> Tage: feedback_bogen.fehl_urlaub/
  fehl_schule/fehl_krank/fehl_sonstige waren in Bestandsboegen als WOCHEN
  erfasst, die UI zeigt sie seit dieser Migration als TAGE. Alle
  bestehenden, nicht-NULL Werte werden deshalb hier EINMALIG mit 5
  multipliziert (siehe _migrate_fehlzeiten_wochen_zu_tagen).

Postgres-safe: neue Tabelle, keine Aenderung an Bestandstabellen. Textspalten
(kommentar, erstellt_von_upn) sowie die Enum-Spalten (typ, quelle) sind
sa.Text()/AutoString, nullable=True OHNE server_default (Anwendungsseite
liefert die Default-Werte beim Anlegen). Datumsspalten sind sa.Date(). Der
Fremdschluessel auf trainee.id traegt ondelete='CASCADE' analog assignment.
trainee_id, dazu ein Index auf trainee_id. Keine Boolean-Spalte in dieser
Tabelle, daher entfaellt die sonst noetige server_default=sa.false()-Regel.

downgrade() droppt die Tabelle ersatzlos -- die Rueckumwandlung in
Assignment-Zeilen wird BEWUSST NICHT versucht (verlustbehaftet: mehrere
zusammengefasste Wochen, SONSTIGES-Abwesenheiten und Teilwochen haben keine
verlustfreie Assignment-Entsprechung). Der Rueckweg im Ernstfall ist die
Datensicherung vor dem Upgrade.
"""
from datetime import date, timedelta
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0012abwesenheit'
down_revision: Union[str, Sequence[str], None] = '0011bogen'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'abwesenheit',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('von_datum', sa.Date(), nullable=False),
        sa.Column('bis_datum', sa.Date(), nullable=False),
        sa.Column('typ', sa.Text(), nullable=True),
        sa.Column('kommentar', sa.Text(), nullable=True),
        sa.Column('quelle', sa.Text(), nullable=True),
        sa.Column('erstellt_von_upn', sa.Text(), nullable=True),
        sa.Column('erstellt_am', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_abwesenheit_trainee_id'), 'abwesenheit', ['trainee_id'], unique=False
    )

    _migrate_urlaub_assignments_to_abwesenheit()
    _migrate_fehlzeiten_wochen_zu_tagen()


def _migrate_fehlzeiten_wochen_zu_tagen() -> None:
    """Einmalige Datenkorrektur: Bestandsboegen (feedback_bogen, angelegt VOR
    dieser Migration) haben die Fehlzeiten-Felder fehl_urlaub/fehl_schule/
    fehl_krank/fehl_sonstige in WOCHEN erfasst. Mit der Umstellung auf
    tagegenaue Abwesenheiten (siehe oben) zeigt die UI diese Felder jetzt als
    TAGE an -- ohne Umrechnung wuerden Bestandswerte fuenffach zu niedrig
    dargestellt. Deshalb werden hier alle bestehenden, nicht-NULL Werte GENAU
    EINMAL mit 5 (Werktage/Woche) multipliziert. Neue Boegen (nach dieser
    Migration) tragen bereits Tage ein -- diese Korrektur darf daher nur
    hier, einmalig, laufen.

    Dialekt-neutral (SQLite + PostgreSQL): reines UPDATE ... SET x = x * 5.
    Im Offline-Modus uebersprungen, analog zur Urlaub-Migration oben.
    """
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    for spalte in ("fehl_urlaub", "fehl_schule", "fehl_krank", "fehl_sonstige"):
        bind.execute(sa.text(
            f"UPDATE feedback_bogen SET {spalte} = {spalte} * 5 WHERE {spalte} IS NOT NULL"
        ))


def _migrate_urlaub_assignments_to_abwesenheit() -> None:
    """Liest alle Assignment-Zeilen mit typ='URLAUB', fasst je Trainee
    aufeinanderfolgende Wochen zu einem Abwesenheit-Eintrag zusammen und
    loescht anschliessend die uebernommenen Assignment-Zeilen.

    Dialekt-neutral: reines SQLAlchemy-Core (sa.text-Select/Delete), keine
    PG- oder SQLite-spezifische Syntax.

    Im Offline-Modus (alembic --sql, reine DDL-Skriptgenerierung ohne echte
    Verbindung) gibt es keine Verbindung, von der Zeilen gelesen werden
    koennten -- die Datenuebernahme wird dann uebersprungen (nur die
    Tabellen-DDL wird ausgegeben); der echte Datenlauf erfolgt online gegen
    eine tatsaechliche Datenbank.
    """
    if context.is_offline_mode():
        return

    bind = op.get_bind()

    rows = bind.execute(
        sa.text(
            "SELECT trainee_id, kw, jahr, source FROM assignment WHERE typ = 'URLAUB'"
        )
    ).fetchall()
    if not rows:
        return

    by_trainee: dict[int, list[tuple[int, int, str]]] = {}
    for trainee_id, kw, jahr, source in rows:
        by_trainee.setdefault(trainee_id, []).append((jahr, kw, source or ''))

    # (trainee_id, kw, jahr)-Tripel, die NICHT in ein gueltiges Datum
    # umgerechnet werden konnten (z. B. kw=53 in einem Jahr mit nur 52
    # ISO-Kalenderwochen -- der Importer akzeptierte 1..53 fuer JEDES Jahr,
    # daher koennen solche Zeilen im Bestand existieren). Diese Zeilen werden
    # NICHT migriert und bleiben unten vom DELETE ausgenommen, damit keine
    # Daten stillschweigend verloren gehen.
    unkonvertierbar: set[tuple[int, int, int]] = set()

    today = date.today()
    insert_stmt = sa.text(
        "INSERT INTO abwesenheit "
        "(trainee_id, von_datum, bis_datum, typ, kommentar, quelle, erstellt_von_upn, erstellt_am) "
        "VALUES (:trainee_id, :von_datum, :bis_datum, 'URLAUB', '', :quelle, '', :erstellt_am)"
    )

    for trainee_id, weeks in by_trainee.items():
        weeks.sort(key=lambda t: (t[0], t[1]))

        # Zu Bloecken aufeinanderfolgender Wochen zusammenfassen. Zwei Wochen
        # gelten als aufeinanderfolgend, wenn der Montag der zweiten Woche
        # gleich Freitag + 3 Tage der ersten Woche ist (naechster Montag).
        block_start: date | None = None
        block_end: date | None = None
        block_source: str | None = None

        def _flush(von: date, bis: date, source: str) -> None:
            quelle = 'SELBST' if source == 'SELBST' else 'PLANER'
            bind.execute(
                insert_stmt,
                {
                    'trainee_id': trainee_id,
                    'von_datum': von,
                    'bis_datum': bis,
                    'quelle': quelle,
                    'erstellt_am': today,
                },
            )

        for jahr, kw, source in weeks:
            try:
                monday = date.fromisocalendar(jahr, kw, 1)
            except ValueError:
                print(
                    f"WARNUNG: Assignment trainee_id={trainee_id} KW {kw}/{jahr} ist "
                    "keine gueltige ISO-Kalenderwoche (Jahr hat wahrscheinlich nur 52 "
                    "Wochen) -- Zeile wird NICHT zu einer Abwesenheit migriert und "
                    "bleibt unveraendert als Assignment(typ='URLAUB') bestehen."
                )
                unkonvertierbar.add((trainee_id, kw, jahr))
                continue
            friday = monday + timedelta(days=4)

            if block_start is not None and block_end is not None and monday == block_end + timedelta(days=3):
                block_end = friday
                # Bei unterschiedlichen Quellen innerhalb eines Blocks bleibt
                # die Quelle der ersten Woche massgeblich.
            else:
                if block_start is not None and block_end is not None and block_source is not None:
                    _flush(block_start, block_end, block_source)
                block_start = monday
                block_end = friday
                block_source = source

        if block_start is not None and block_end is not None and block_source is not None:
            _flush(block_start, block_end, block_source)

    if unkonvertierbar:
        # Alle URLAUB-Zeilen loeschen AUSSER den nicht konvertierbaren
        # (trainee_id, kw, jahr)-Tripeln -- dialekt-neutrale OR-Bedingung
        # statt Tupel-IN (funktioniert auf SQLite und PostgreSQL gleich).
        conditions = []
        params: dict[str, int] = {}
        for i, (trainee_id, kw, jahr) in enumerate(sorted(unkonvertierbar)):
            conditions.append(f"(trainee_id = :tid{i} AND kw = :kw{i} AND jahr = :jahr{i})")
            params[f"tid{i}"] = trainee_id
            params[f"kw{i}"] = kw
            params[f"jahr{i}"] = jahr
        exclude_clause = " OR ".join(conditions)
        bind.execute(
            sa.text(f"DELETE FROM assignment WHERE typ = 'URLAUB' AND NOT ({exclude_clause})"),
            params,
        )
        print(
            f"WARNUNG: {len(unkonvertierbar)} Assignment-Zeile(n) mit typ='URLAUB' "
            "konnten wegen ungueltiger KW/Jahr-Kombination nicht migriert werden "
            "und wurden NICHT geloescht (siehe Warnungen oben)."
        )
    else:
        bind.execute(sa.text("DELETE FROM assignment WHERE typ = 'URLAUB'"))


def downgrade() -> None:
    op.drop_index(op.f('ix_abwesenheit_trainee_id'), table_name='abwesenheit')
    op.drop_table('abwesenheit')
