"""Bulk-Import-Service: Parsing, Validierung und Persistierung.

Unterstuetzt zwei Import-Typen:
  A) Schulplan-Wochen (SchoolPlanWeek) fuer einen bestehenden SchoolPlan
  B) Vergangene Einsaetze (Assignment) fuer ein Lehrjahr

Parsing:
  - Delimiter wird automatisch erkannt: Tab, Semikolon oder Komma.
  - Optionale Kopfzeile wird erkannt und uebersprungen.
  - Leere Zeilen werden ignoriert.

Rueckgabe: ParseResult mit gueltigen Zeilen und Fehlerzeilen.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
)
from app.utils.kw import iter_schoolyear_weeks


# ── Typ-Kuerzel-Mapping ───────────────────────────────────────────────────────

_SCHOOL_WEEK_TYP_MAP: dict[str, SchoolWeekTyp] = {
    "BERUFSSCHULE": SchoolWeekTyp.BERUFSSCHULE,
    "BS": SchoolWeekTyp.BERUFSSCHULE,
    "UNI": SchoolWeekTyp.UNI,
    "HS": SchoolWeekTyp.UNI,
    "HOCHSCHULE": SchoolWeekTyp.UNI,
}

_ASSIGNMENT_TYP_MAP: dict[str, AssignmentTyp] = {
    "ABTEILUNG": AssignmentTyp.ABTEILUNG,
    "BERUFSSCHULE": AssignmentTyp.BERUFSSCHULE,
    "BS": AssignmentTyp.BERUFSSCHULE,
    "UNI": AssignmentTyp.UNI,
    "HS": AssignmentTyp.UNI,
    "HOCHSCHULE": AssignmentTyp.UNI,
    "URLAUB": AssignmentTyp.URLAUB,
    "U": AssignmentTyp.URLAUB,
    "FREI": AssignmentTyp.FREI,
    "F": AssignmentTyp.FREI,
}

# Kopfzeilen-Schluesselwoerter: falls die erste Zeile eines dieser Woerter (case-insensitive)
# enthaelt, wird sie als Headerzeile erkannt und uebersprungen.
_HEADER_KEYWORDS = frozenset({"kw", "woche", "azubi", "trainee", "name", "typ", "type", "jahr", "year"})


# ── Datenklassen ──────────────────────────────────────────────────────────────

@dataclass
class ErrorRow:
    row_index: int          # 1-basiert, bezogen auf die Datenzeilen (nach Header-Entfernung)
    raw: str                # Originalzeile als String
    reason: str             # Fehlermeldung


@dataclass
class ParsedSchoolWeek:
    kw: int
    jahr: int
    typ: SchoolWeekTyp
    raw: str = ""


@dataclass
class ParsedAssignment:
    trainee_id: int
    trainee_name: str
    kw: int
    jahr: int
    typ: AssignmentTyp
    abteilung_id: int | None
    abteilung_code: str
    raw: str = ""


@dataclass
class SchoolWeekParseResult:
    valid: list[ParsedSchoolWeek] = field(default_factory=list)
    errors: list[ErrorRow] = field(default_factory=list)


@dataclass
class AssignmentParseResult:
    valid: list[ParsedAssignment] = field(default_factory=list)
    errors: list[ErrorRow] = field(default_factory=list)


# ── Delimiter-Erkennung und Zeilenzerlegung ───────────────────────────────────

def _detect_delimiter(text: str) -> str:
    """Erkennt Tab, Semikolon oder Komma als Trennzeichen.

    Prueft die ersten Nicht-Leerzeilen und zaehlt Vorkommen.
    Standard-Fallback: Tab.
    """
    candidates = ["\t", ";", ","]
    sample_lines = [l for l in text.splitlines() if l.strip()][:5]
    if not sample_lines:
        return "\t"

    counts: dict[str, int] = {d: 0 for d in candidates}
    for line in sample_lines:
        for d in candidates:
            counts[d] += line.count(d)

    best = max(candidates, key=lambda d: counts[d])
    return best if counts[best] > 0 else "\t"


def _split_rows(text: str) -> list[list[str]]:
    """Zerlegt den Rohtext in Zeilen → Spalten.

    - Delimiter wird automatisch erkannt.
    - Leere Zeilen werden ignoriert.
    - Fuehrendes/nachfolgendes Whitespace pro Zelle wird entfernt.
    """
    delim = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = []
    for row in reader:
        stripped = [cell.strip() for cell in row]
        if any(stripped):  # Zeile nicht leer
            rows.append(stripped)
    return rows


def _is_header(row: list[str]) -> bool:
    """True wenn die Zeile aussieht wie eine Kopfzeile."""
    return any(cell.lower() in _HEADER_KEYWORDS for cell in row)


def _parse_kw_jahr(kw_raw: str, jahr_raw: str) -> tuple[int, int] | str:
    """Gibt (kw, jahr) zurueck oder einen Fehlerstring."""
    try:
        kw = int(kw_raw)
        jahr = int(jahr_raw)
    except (ValueError, TypeError):
        return f"KW/Jahr ungueltig: '{kw_raw}'/'{jahr_raw}'"
    if not (1 <= kw <= 53):
        return f"KW {kw} ausserhalb des gueltigen Bereichs (1-53)"
    if not (2000 <= jahr <= 2100):
        return f"Jahr {jahr} ausserhalb des gueltigen Bereichs"
    return kw, jahr


# ── Import A: Schulplan-Wochen ────────────────────────────────────────────────

def parse_school_weeks(text: str) -> SchoolWeekParseResult:
    """Parst Rohtext zu SchoolPlanWeek-Daten (ohne DB-Zugriff).

    Erwartete Spalten: KW, Jahr, Typ
    """
    result = SchoolWeekParseResult()
    rows = _split_rows(text)
    if not rows:
        return result

    # Headerzeile ueberpruefen
    data_rows = rows[1:] if _is_header(rows[0]) else rows

    for idx, row in enumerate(data_rows, start=1):
        raw = "\t".join(row)
        if len(row) < 3:
            result.errors.append(ErrorRow(idx, raw, f"Zu wenige Spalten ({len(row)}, erwartet: 3: KW, Jahr, Typ)"))
            continue

        kw_raw, jahr_raw, typ_raw = row[0], row[1], row[2]

        kw_jahr = _parse_kw_jahr(kw_raw, jahr_raw)
        if isinstance(kw_jahr, str):
            result.errors.append(ErrorRow(idx, raw, kw_jahr))
            continue
        kw, jahr = kw_jahr

        typ_key = typ_raw.upper().strip()
        typ = _SCHOOL_WEEK_TYP_MAP.get(typ_key)
        if typ is None:
            result.errors.append(ErrorRow(idx, raw, f"Unbekannter Typ '{typ_raw}' (erlaubt: BS/BERUFSSCHULE, HS/UNI)"))
            continue

        result.valid.append(ParsedSchoolWeek(kw=kw, jahr=jahr, typ=typ, raw=raw))

    return result


def apply_school_weeks(
    db: Session,
    plan_id: int,
    parsed: list[ParsedSchoolWeek],
) -> tuple[list[ParsedSchoolWeek], list[ErrorRow]]:
    """Schreibt gueltige Schulwochen in die DB.

    Bereits vorhandene (plan_id, kw, jahr) werden uebersprungen und gemeldet.
    Gibt (geschriebene, uebersprungene) zurueck.
    """
    from app.services.school_sync import sync_class

    written: list[ParsedSchoolWeek] = []
    skipped: list[ErrorRow] = []

    plan = db.get(SchoolPlan, plan_id)
    if plan is None:
        return [], [ErrorRow(0, "", f"SchoolPlan #{plan_id} nicht gefunden")]

    for i, pw in enumerate(parsed, start=1):
        existing = db.exec(
            select(SchoolPlanWeek).where(
                SchoolPlanWeek.plan_id == plan_id,
                SchoolPlanWeek.kw == pw.kw,
                SchoolPlanWeek.jahr == pw.jahr,
            )
        ).first()
        if existing:
            skipped.append(ErrorRow(i, pw.raw, f"KW {pw.kw}/{pw.jahr} bereits vorhanden – uebersprungen"))
            continue

        db.add(SchoolPlanWeek(plan_id=plan_id, kw=pw.kw, jahr=pw.jahr, typ=pw.typ))
        written.append(pw)

    db.commit()

    # Schulwochen als AUTO-Einsaetze materialisieren
    if written:
        sync_class(db, plan.klasse_id)

    return written, skipped


# ── Import B: Einsaetze ───────────────────────────────────────────────────────

def parse_assignments(text: str, db: Session, schoolyear_id: str) -> AssignmentParseResult:
    """Parst Rohtext zu Assignment-Daten und validiert gegen die DB.

    Erwartete Spalten: Azubi, KW, Jahr, Abteilung[, Typ]

    Azubi: "Nachname, Vorname" (case-insensitive)
    Abteilung: Department.code (case-insensitive)
    Typ: optional, Default ABTEILUNG
    """
    result = AssignmentParseResult()
    rows = _split_rows(text)
    if not rows:
        return result

    # Lookup-Tabellen aufbauen (case-insensitive)
    trainees_all = db.exec(select(Trainee)).all()
    trainee_map: dict[str, Trainee] = {}
    for t in trainees_all:
        key = f"{t.nachname.lower()}, {t.vorname.lower()}"
        trainee_map[key] = t

    depts_all = db.exec(select(Department)).all()
    dept_map: dict[str, Department] = {d.code.lower(): d for d in depts_all}

    # Schuljahr pruefen
    schoolyear = db.get(Schoolyear, schoolyear_id)
    if schoolyear is None:
        # Fehler fuer alle Zeilen – Schuljahr fehlt
        data_rows = rows[1:] if _is_header(rows[0]) else rows
        for idx, row in enumerate(data_rows, start=1):
            result.errors.append(ErrorRow(idx, "\t".join(row), f"Schuljahr '{schoolyear_id}' nicht gefunden"))
        return result

    data_rows = rows[1:] if _is_header(rows[0]) else rows

    for idx, row in enumerate(data_rows, start=1):
        raw = "\t".join(row)
        if len(row) < 4:
            result.errors.append(ErrorRow(idx, raw, f"Zu wenige Spalten ({len(row)}, erwartet: mind. 4: Azubi, KW, Jahr, Abteilung)"))
            continue

        azubi_raw, kw_raw, jahr_raw, dept_raw = row[0], row[1], row[2], row[3]
        typ_raw = row[4] if len(row) >= 5 else ""

        # Azubi matchen
        azubi_key = azubi_raw.strip().lower()
        trainee = trainee_map.get(azubi_key)
        if trainee is None:
            result.errors.append(ErrorRow(idx, raw, f"Azubi '{azubi_raw}' nicht gefunden (Format: 'Nachname, Vorname')"))
            continue

        # KW/Jahr pruefen
        kw_jahr = _parse_kw_jahr(kw_raw, jahr_raw)
        if isinstance(kw_jahr, str):
            result.errors.append(ErrorRow(idx, raw, kw_jahr))
            continue
        kw, jahr = kw_jahr

        # Typ ermitteln (optional, Default ABTEILUNG)
        if typ_raw.strip():
            typ_key = typ_raw.strip().upper()
            typ = _ASSIGNMENT_TYP_MAP.get(typ_key)
            if typ is None:
                result.errors.append(ErrorRow(idx, raw, f"Unbekannter Typ '{typ_raw}'"))
                continue
        else:
            typ = AssignmentTyp.ABTEILUNG

        # Abteilung matchen (nur bei ABTEILUNG-Typ erforderlich)
        abteilung_id: int | None = None
        abteilung_code = ""
        if typ == AssignmentTyp.ABTEILUNG:
            dept_key = dept_raw.strip().lower()
            dept = dept_map.get(dept_key)
            if dept is None:
                result.errors.append(ErrorRow(idx, raw, f"Abteilung '{dept_raw}' nicht gefunden (Code, case-insensitive)"))
                continue
            abteilung_id = dept.id
            abteilung_code = dept.code
        else:
            # Bei nicht-Abteilungs-Typen kann die Spalte leer oder irrelevant sein
            abteilung_code = dept_raw.strip()

        result.valid.append(ParsedAssignment(
            trainee_id=trainee.id,
            trainee_name=f"{trainee.nachname}, {trainee.vorname}",
            kw=kw,
            jahr=jahr,
            typ=typ,
            abteilung_id=abteilung_id,
            abteilung_code=abteilung_code,
            raw=raw,
        ))

    return result


# ── Import B2: Matrix-/Breitformat ───────────────────────────────────────────

# Muster für KW-Spaltenköpfe: "KW36", "KW 36", "36"
_KW_HEADER_RE = re.compile(r"^(KW\s*)?(\d{1,2})$", re.IGNORECASE)


def _kw_to_jahr(schoolyear: Schoolyear) -> dict[int, int]:
    """Gibt ein Dict {kw: jahr} zurück, basierend auf iter_schoolyear_weeks.

    Bei Jahreswechsel (z.B. KW52 2025, KW1 2026) wird die korrekte Jahr-
    Zuordnung über die chronologische Reihenfolge ermittelt.
    """
    result: dict[int, int] = {}
    for kw, jahr in iter_schoolyear_weeks(
        schoolyear.start_kw, schoolyear.start_year,
        schoolyear.end_kw, schoolyear.end_year,
    ):
        # Erste Zuordnung gewinnt (Jahreswechsel: KW1 gehört zum Folgejahr)
        if kw not in result:
            result[kw] = jahr
    return result


def _looks_like_matrix(rows: list[list[str]]) -> bool:
    """True, wenn eine der ersten ~3 Zeilen ≥2 KW-Spaltenköpfe enthält.

    KW-Spaltenköpfe haben die Form 'KW36', 'KW 36' oder '36' — sie treten
    im Langformat nicht auf (dort stehen Zahlen als Werte, nicht als Header).
    ≥2 ist ausreichend, um Langformat (Azubi|KW|Jahr|Abt) sicher abzugrenzen.
    """
    for row in rows[:3]:
        kw_count = sum(1 for cell in row if _KW_HEADER_RE.match(cell))
        if kw_count >= 2:
            return True
    return False


def parse_assignments_matrix(
    text: str,
    db: Session,
    schoolyear_id: str,
) -> AssignmentParseResult:
    """Parst Matrixformat (Breitformat aus Excel) zu Assignment-Daten.

    Kopfzeile: Woche | (leer) | KW36 | KW37 | … (Spalte 0/1 ignoriert)
    Datenzeilen: Azubi-Name (mit optionalem Klammerzusatz) | (leer) | Code …
    """
    result = AssignmentParseResult()
    rows = _split_rows(text)
    if not rows:
        return result

    # Schuljahr prüfen
    schoolyear = db.get(Schoolyear, schoolyear_id)
    if schoolyear is None:
        for idx, row in enumerate(rows, start=1):
            result.errors.append(ErrorRow(idx, "\t".join(row), f"Schuljahr '{schoolyear_id}' nicht gefunden"))
        return result

    kw_jahr_map = _kw_to_jahr(schoolyear)

    # Kopfzeile finden: erste Zeile mit ≥2 KW-Zellen
    header_row_idx: int | None = None
    for i, row in enumerate(rows):
        kw_count = sum(1 for cell in row if _KW_HEADER_RE.match(cell))
        if kw_count >= 2:
            header_row_idx = i
            break

    if header_row_idx is None:
        result.errors.append(ErrorRow(0, "", "Keine KW-Kopfzeile gefunden (mind. 2 KW-Spalten erwartet)"))
        return result

    header_row = rows[header_row_idx]

    # Spalten-Mapping aufbauen: j -> (kw, jahr)
    # Bereits gemeldete fehlende KWs nicht doppelt melden
    reported_missing_kw: set[int] = set()
    kw_cols: list[tuple[int, int, int]] = []  # (spalten_index, kw, jahr)
    for j, cell in enumerate(header_row):
        m = _KW_HEADER_RE.match(cell)
        if m:
            kw = int(m.group(2))
            jahr = kw_jahr_map.get(kw)
            if jahr is None:
                if kw not in reported_missing_kw:
                    result.errors.append(ErrorRow(0, cell, f"KW {kw} nicht im Lehrjahr '{schoolyear_id}' – Spalte ignoriert"))
                    reported_missing_kw.add(kw)
            else:
                kw_cols.append((j, kw, jahr))

    if not kw_cols:
        result.errors.append(ErrorRow(0, "", "Keine gültigen KW-Spalten im Lehrjahr gefunden"))
        return result

    # Lookup-Tabellen aufbauen
    trainees_all = db.exec(select(Trainee)).all()
    trainee_map: dict[str, Trainee] = {}
    for t in trainees_all:
        nn = t.nachname.lower()
        vn = t.vorname.lower()
        # Drei Schlüssel je Trainee (Leerzeichen normalisiert)
        for key in (f"{nn}, {vn}", f"{nn} {vn}", f"{vn} {nn}"):
            key_norm = re.sub(r"\s+", " ", key).strip()
            trainee_map[key_norm] = t

    depts_all = db.exec(select(Department)).all()
    dept_map: dict[str, Department] = {d.code.lower(): d for d in depts_all}

    # Datenzeilen verarbeiten (alles nach der Kopfzeile)
    data_rows = rows[header_row_idx + 1:]
    for idx, row in enumerate(data_rows, start=1):
        # Zeile still überspringen wenn in keiner KW-Spalte ein Wert steht
        has_value = any(
            j < len(row) and row[j].strip()
            for j, _kw, _jahr in kw_cols
        )
        if not has_value:
            continue

        name_raw = row[0] if row else ""
        # Klammerzusatz entfernen, Leerzeichen normalisieren
        name_clean = re.sub(r"\(.*?\)", "", name_raw).strip()
        name_clean = re.sub(r"\s+", " ", name_clean).lower()

        trainee = trainee_map.get(name_clean)
        if trainee is None:
            result.errors.append(ErrorRow(
                idx, "\t".join(row),
                f"Azubi '{name_raw.strip()}' nicht gefunden",
            ))
            continue

        for j, kw, jahr in kw_cols:
            if j >= len(row):
                continue
            code = row[j].strip()
            if not code:
                continue

            code_upper = code.upper()
            typ = _ASSIGNMENT_TYP_MAP.get(code_upper)

            if typ is not None and typ != AssignmentTyp.ABTEILUNG:
                # BS, Uni, Urlaub, Frei
                result.valid.append(ParsedAssignment(
                    trainee_id=trainee.id,
                    trainee_name=f"{trainee.nachname}, {trainee.vorname}",
                    kw=kw,
                    jahr=jahr,
                    typ=typ,
                    abteilung_id=None,
                    abteilung_code="",
                    raw=f"{name_raw}\tKW{kw}\t{code}",
                ))
            else:
                # Abteilungs-Kürzel
                dept = dept_map.get(code.lower())
                if dept is None:
                    result.errors.append(ErrorRow(
                        idx, "\t".join(row),
                        f"Unbekannter Code '{code}' in KW {kw} – weder Sondertyp noch bekannte Abteilung",
                    ))
                else:
                    result.valid.append(ParsedAssignment(
                        trainee_id=trainee.id,
                        trainee_name=f"{trainee.nachname}, {trainee.vorname}",
                        kw=kw,
                        jahr=jahr,
                        typ=AssignmentTyp.ABTEILUNG,
                        abteilung_id=dept.id,
                        abteilung_code=dept.code,
                        raw=f"{name_raw}\tKW{kw}\t{code}",
                    ))

    return result


def parse_assignments_auto(
    text: str,
    db: Session,
    schoolyear_id: str,
) -> AssignmentParseResult:
    """Auto-Dispatcher: Matrix- oder Langformat wird automatisch erkannt.

    Wenn die Eingabe eine KW-Kopfzeile (≥3 KW-Spalten) enthält, wird das
    Matrix-Format verwendet; andernfalls das bestehende Langformat.
    """
    rows = _split_rows(text)
    if _looks_like_matrix(rows):
        return parse_assignments_matrix(text, db, schoolyear_id)
    return parse_assignments(text, db, schoolyear_id)


def apply_assignments(
    db: Session,
    schoolyear_id: str,
    parsed: list[ParsedAssignment],
) -> tuple[list[ParsedAssignment], list[ErrorRow]]:
    """Schreibt gueltige Einsaetze in die DB.

    Bereits vorhandene (trainee_id, kw, jahr) werden uebersprungen und gemeldet.
    Gibt (geschriebene, uebersprungene) zurueck.
    """
    written: list[ParsedAssignment] = []
    skipped: list[ErrorRow] = []

    for i, pa in enumerate(parsed, start=1):
        existing = db.exec(
            select(Assignment).where(
                Assignment.trainee_id == pa.trainee_id,
                Assignment.kw == pa.kw,
                Assignment.jahr == pa.jahr,
            )
        ).first()
        if existing:
            skipped.append(ErrorRow(
                i, pa.raw,
                f"{pa.trainee_name} KW {pa.kw}/{pa.jahr} bereits vorhanden – uebersprungen"
            ))
            continue

        db.add(Assignment(
            trainee_id=pa.trainee_id,
            schoolyear_id=schoolyear_id,
            kw=pa.kw,
            jahr=pa.jahr,
            typ=pa.typ,
            abteilung_id=pa.abteilung_id,
            source=AssignmentSource.IMPORT,
        ))
        written.append(pa)

    db.commit()
    return written, skipped
