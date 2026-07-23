"""Export/Import aller Stamm- und Bewegungsdaten als ZIP (eine CSV je Tabelle).

export_zip(db)      -> ZIP-Bytes, eine CSV je Registry-Tabelle (Header + Zeilen).
import_zip(db, zip) -> ERSETZT ALLE Registry-Tabellen durch den ZIP-Inhalt:
    1. TraineeClass.next_class_id ueberall auf NULL (Self-FK entschaerfen).
    2. Alle Registry-Tabellen in UMGEKEHRTER Registry-Reihenfolge leeren
       (Kinder vor Eltern, FK-sicher).
    3. Je Tabelle (in Registry-Reihenfolge) aus der jeweiligen CSV neu
       einfuegen, mit den Original-IDs. TraineeClass in zwei Phasen: erst
       ohne next_class_id, danach next_class_id per Update nachziehen.
       Fehlt eine Tabelle im ZIP, bleibt sie leer (Zaehler 0).
    4. PostgreSQL: Sequenzen der Integer-PK-Tabellen auf MAX(id) setzen
       (sonst kollidieren kuenftige Inserts). SQLite: kein Schritt noetig.

Die komplette Operation laeuft in EINER Transaktion: bei jedem Fehler wird
db.rollback() aufgerufen und eine Exception mit Datei- und Zeilenkontext
geworfen (kein Teil-Import).
"""

from __future__ import annotations

import csv
import io
import types
import typing
import zipfile
from datetime import date
from enum import Enum

from sqlalchemy import text
from sqlmodel import Session, select

from app.models import (
    Assignment,
    Department,
    DepartmentKategorie,
    EinsatzVorschlag,
    SchoolHoliday,
    SchoolPlan,
    SchoolPlanWeek,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeWish,
)

# FK-sichere Reihenfolge: Eltern zuerst. Import leert in umgekehrter, fuellt
# in dieser (vorwaerts-)Reihenfolge wieder auf.
TABELLEN_REGISTRY: list[tuple[str, type]] = [
    ("schoolyears", Schoolyear),
    ("klassen", TraineeClass),
    ("abteilungskategorien", DepartmentKategorie),
    ("abteilungen", Department),
    ("trainees", Trainee),
    ("schulplaene", SchoolPlan),
    ("schulplan_wochen", SchoolPlanWeek),
    ("ferien", SchoolHoliday),
    ("einsaetze", Assignment),
    ("memberships", TraineeClassMembership),
    ("wuensche", TraineeWish),
    ("vorschlaege", EinsatzVorschlag),
]


def _feldnamen(model: type) -> list[str]:
    return list(model.model_fields.keys())


def _serialize(value: object) -> str:
    """Serialisiert einen Modellwert fuer die CSV-Zelle."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return str(value)


def _unwrap_optional(annotation: object) -> object:
    """Loest 'X | None' (bzw. Optional[X]) zu X auf; sonst unveraendert."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is getattr(types, "UnionType", object()):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _cast(raw: str, annotation: object) -> object:
    """Castet einen CSV-Rohwert (str) zurueck auf den Modell-Zieltyp.

    Leerer String bei einem optionalen Feld (X | None) -> None. Bei einem
    NICHT optionalen str-Feld (z. B. notizen mit default="") ist "" jedoch
    ein legitimer Wert und bleibt "" (sonst wuerde None an ein Pflicht-
    str-Feld uebergeben -> Validierungsfehler beim Modell-Konstruktor).
    """
    real_type = _unwrap_optional(annotation)
    is_optional = real_type is not annotation
    if raw == "":
        if real_type is str and not is_optional:
            return ""
        return None
    if real_type is bool:
        return raw == "true"
    if real_type is int:
        return int(raw)
    if real_type is date:
        return date.fromisoformat(raw)
    if isinstance(real_type, type) and issubclass(real_type, Enum):
        return real_type(raw)
    return raw


def _has_integer_pk(model: type) -> bool:
    ann = _unwrap_optional(model.model_fields["id"].annotation)
    return ann is int


# Erklaerungstext fuers Export-ZIP. import_zip() liest ausschliesslich die in
# TABELLEN_REGISTRY gelisteten *.csv-Dateien (siehe Schritt 3 dort) und
# ueberspringt jede andere Datei im ZIP automatisch -- LIESMICH.txt wird beim
# Wieder-Import also stillschweigend ignoriert.
_LIESMICH_TEXT = """\
WILBETH – DATENEXPORT
=====================

Zweck dieses ZIPs
-----------------
Dieses ZIP enthaelt eine vollstaendige Datensicherung aller Wilbeth-Stamm-
und Bewegungsdaten (eine CSV-Datei je Tabelle). Es dient zwei Zwecken:

  1. Backup / Archivierung.
  2. Wieder-Einspielen ueber den "Ersetzen"-Import: dabei werden ALLE
     Tabellen in der App durch den Inhalt dieses ZIPs ERSETZT (kein
     Zusammenfuehren, kein Teil-Import).

Diese LIESMICH.txt ist nur zur Information. Sie ist keine Tabelle und wird
vom Import automatisch uebersprungen (unbekannte Dateien im ZIP werden beim
Ersetzen-Import ignoriert).

Wichtigste Spalten je Datei
----------------------------
- schoolyears.csv           Ausbildungsjahre (id, Start/Ende als KW+Jahr,
                             archiviert-Flag).
- klassen.csv                Klassen (id, name, Unterrichtstyp, Schultage,
                             next_class_id = Nachfolgeklasse beim
                             Jahreswechsel).
- abteilungskategorien.csv   Abteilungs-Kategorien.
- abteilungen.csv            Abteilungen (Code, Name, Verantwortliche, ...).
- trainees.csv               Trainees/Azubis/DH-Studenten. Wichtigste Spalte:
                             ausbildungsbeginn (Startdatum) und

                             *** klasse_id = EINSTIEGSKLASSE (Anker) ***
                             Das ist die Klasse BEIM AUSBILDUNGSSTART, NICHT
                             die aktuelle Klasse! Die IDs sind in klassen.csv
                             nachschlagbar. Die aktuelle Klasse wird von
                             Wilbeth immer live aus ausbildungsbeginn +
                             Einstiegsklasse berechnet und steht bewusst in
                             KEINER CSV-Datei.

- schulplaene.csv            Schulplaene je Klasse/Ausbildungsjahr.
- schulplan_wochen.csv       Einzelne Schulwochen je Schulplan.
- ferien.csv                 Schulferien.
- einsaetze.csv              Einsaetze/Belegungen je Trainee und Woche.
- memberships.csv            AUSNAHME-Zuweisungen (Overrides): eine Zeile nur
                             dann, wenn ein Trainee in einem bestimmten
                             Ausbildungsjahr abweichend von der berechneten
                             Klasse eingeordnet wurde (z. B. Wiederholer,
                             Klassenwechsel). Im Normalfall ist diese Datei
                             LEER.
- wuensche.csv               Abteilungs-Wuensche der Trainees.
- vorschlaege.csv            Einsatzvorschlaege von Ausbildern.
"""


def export_zip(db: Session) -> bytes:
    """Exportiert alle Registry-Tabellen als ZIP (eine CSV je Tabelle) + LIESMICH.txt."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for dateiname, model in TABELLEN_REGISTRY:
            felder = _feldnamen(model)
            rows = db.exec(select(model)).all()
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(felder)
            for row in rows:
                writer.writerow([_serialize(getattr(row, f)) for f in felder])
            # utf-8-sig: BOM, damit Excel die CSV korrekt als UTF-8 erkennt.
            zf.writestr(f"{dateiname}.csv", out.getvalue().encode("utf-8-sig"))
        zf.writestr("LIESMICH.txt", _LIESMICH_TEXT.encode("utf-8-sig"))
    return buffer.getvalue()


def import_zip(db: Session, zip_bytes: bytes) -> dict[str, int]:
    """Ersetzt ALLE Registry-Tabellen durch den Inhalt des ZIP.

    Rueckgabe: {dateiname: anzahl_importierter_zeilen}. Bei jedem Fehler wird
    die Transaktion zurueckgerollt und eine ValueError mit Datei+Zeile
    geworfen.
    """
    counts: dict[str, int] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            namen_im_zip = set(zf.namelist())

            # (1) Self-FK von TraineeClass entschaerfen, bevor irgendetwas
            # geloescht wird (sonst blockiert die FK-Constraint das Loeschen
            # referenzierter Klassen unter PostgreSQL).
            for klasse in db.exec(select(TraineeClass)).all():
                klasse.next_class_id = None
                db.add(klasse)
            db.flush()

            # (2) Alle Registry-Tabellen leeren, Kinder vor Eltern.
            for _dateiname, model in reversed(TABELLEN_REGISTRY):
                for row in db.exec(select(model)).all():
                    db.delete(row)
                db.flush()

            # (3) Neu einfuegen, Eltern vor Kindern, mit Original-IDs.
            next_class_updates: list[tuple[int, int]] = []  # (klasse_id, next_class_id)

            for dateiname, model in TABELLEN_REGISTRY:
                dateipfad = f"{dateiname}.csv"
                if dateipfad not in namen_im_zip:
                    counts[dateiname] = 0
                    continue

                felder = _feldnamen(model)
                annotations = {f: model.model_fields[f].annotation for f in felder}
                roh_text = zf.read(dateipfad).decode("utf-8-sig")
                reader = csv.reader(io.StringIO(roh_text))
                header = next(reader, None)

                anzahl = 0
                zeilen_nr = 1  # Header zaehlt als Zeile 1
                if header is not None:
                    for zeile in reader:
                        zeilen_nr += 1
                        try:
                            werte = dict(zip(header, zeile))
                            kwargs: dict[str, object] = {}
                            for feld in felder:
                                if model is TraineeClass and feld == "next_class_id":
                                    continue  # Phase 2, nach allen Inserts
                                kwargs[feld] = _cast(werte.get(feld, ""), annotations[feld])
                            instanz = model(**kwargs)
                            db.add(instanz)
                            db.flush()
                            if model is TraineeClass:
                                roh_next = werte.get("next_class_id", "")
                                if roh_next:
                                    next_class_updates.append((kwargs["id"], int(roh_next)))
                            anzahl += 1
                        except Exception as exc:
                            raise ValueError(
                                f"{dateipfad}, Zeile {zeilen_nr}: {exc}"
                            ) from exc
                counts[dateiname] = anzahl

            # TraineeClass Phase 2: next_class_id nachziehen.
            for klasse_id, next_id in next_class_updates:
                klasse = db.get(TraineeClass, klasse_id)
                if klasse is not None:
                    klasse.next_class_id = next_id
                    db.add(klasse)
            db.flush()

            # (4) PostgreSQL: Sequenzen der Integer-PK-Tabellen nachziehen.
            if db.get_bind().dialect.name == "postgresql":
                for _dateiname, model in TABELLEN_REGISTRY:
                    if not _has_integer_pk(model):
                        continue
                    tabelle = model.__tablename__
                    db.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{tabelle}', 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {tabelle}), 1))"
                        )
                    )

        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
