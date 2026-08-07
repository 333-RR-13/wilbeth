"""Utilities fuer Department.verantwortliche: Parsen/Serialisieren der
UPN-Liste sowie die Umkehrung Person -> Abteilungen fuer die zentrale
Ausbilder-Verwaltung (siehe app/routers/ausbilder_verwaltung.py).

Department.verantwortliche ist reiner Freitext, Trenner Komma/Semikolon/
Newline (siehe app/services/auth_service.allowed_dept_ids -- dieselbe
Trennzeichen-Logik). Diese Datei buendelt das robuste Parsen/Schreiben
dieses Feldes an einer Stelle, damit Router UND Tests dieselbe Logik
nutzen -- analog zum Stil von app/services/dept_history.py.
"""

import re

from sqlmodel import Session, select

from app.models.department import Department


def parse_verantwortliche(raw: str | None) -> list[str]:
    """Zerlegt eine Department.verantwortliche-Zeichenkette in bereinigte
    Eintraege.

    Trenner: Komma, Semikolon, Newline. Jeder Eintrag wird getrimmt; leere
    Eintraege (z. B. durch doppelte Trenner oder Leerzeilen) werden
    verworfen. None/leer -> leere Liste. Rein defensiv: krumme Eingaben
    fuehren nie zu einer Exception.
    """
    if not raw:
        return []
    return [teil.strip() for teil in re.split(r"[,;\n]", raw) if teil.strip()]


def serialize_verantwortliche(eintraege: list[str]) -> str:
    """Fuegt eine Liste von Eintraegen wieder zu einem
    Department.verantwortliche-String zusammen (Trenner ', ')."""
    return ", ".join(eintraege)


def people_by_upn(db: Session) -> dict[str, list[Department]]:
    """Kehrt Department.verantwortliche ueber ALLE Abteilungen um: liefert
    je (case-insensitiv normalisierter, kleingeschriebener) UPN die Liste
    der Department-Objekte, in denen diese Person eingetragen ist.

    Gleiche UPN in unterschiedlicher Gross-/Kleinschreibung wird zu EINER
    Person zusammengefasst -- kanonische Darstellung ist die kleingeschriebene
    Form. Rueckgabe-Dict ist alphabetisch nach UPN sortiert; je Person sind
    die Abteilungen nach Department.code sortiert (da departments bereits
    sortiert eingelesen werden).
    """
    departments = db.exec(select(Department).order_by(Department.code)).all()
    grouped: dict[str, list[Department]] = {}
    for dept in departments:
        for eintrag in parse_verantwortliche(dept.verantwortliche):
            key = eintrag.lower()
            grouped.setdefault(key, []).append(dept)
    return {upn: grouped[upn] for upn in sorted(grouped)}


def sync_assignments(db: Session, upn: str, dept_ids: set[int]) -> int:
    """Setzt die Abteilungs-Zuordnung einer UPN auf genau dept_ids.

    Fuer JEDE Abteilung wird verantwortliche neu geparst, ein evtl.
    vorhandener Eintrag dieser UPN (case-insensitiver Vergleich, auch bei
    mehrfachem Vorkommen) entfernt. Steht die Abteilungs-ID in dept_ids,
    wird danach genau EIN Eintrag wieder angehaengt -- dedupliziert, keine
    doppelten Eintraege derselben UPN in derselben Abteilung.

    Schreibweise beim Wiederanhaengen: wenn die Abteilung die UPN bereits
    (in irgendeiner Gross-/Kleinschreibung) enthielt, bleibt genau diese
    bisherige Schreibweise erhalten. Bei einer Neuzuordnung (die Abteilung
    hatte die UPN vorher nicht) wird die per Parameter uebergebene
    Schreibweise verwendet (z. B. die vom User im Formular eingegebene).

    Alle anderen Eintraege (andere Personen) in jedem verantwortliche-Feld
    bleiben unveraendert erhalten -- nur der Eintrag der uebergebenen UPN
    wird veraendert.

    Gibt die Anzahl der Abteilungen zurueck, denen die UPN danach
    zugeordnet ist.
    """
    normalized_upn = upn.strip().lower()
    departments = db.exec(select(Department)).all()
    assigned = 0
    for dept in departments:
        eintraege = parse_verantwortliche(dept.verantwortliche)
        bisherige_schreibweise = next(
            (e for e in eintraege if e.lower() == normalized_upn), None
        )
        rest = [e for e in eintraege if e.lower() != normalized_upn]
        if dept.id in dept_ids:
            rest.append(bisherige_schreibweise if bisherige_schreibweise is not None else upn.strip())
            assigned += 1
        neuer_wert = serialize_verantwortliche(rest)
        if neuer_wert != (dept.verantwortliche or ""):
            dept.verantwortliche = neuer_wert
            db.add(dept)
    db.commit()
    return assigned
