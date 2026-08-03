"""Hilfsfunktionen fuer Abwesenheiten (Overlay-Modell statt Assignment-URLAUB):
Wochen-Markierungen fuer die Einsatzmatrix (abwesenheit_map), Fehlzeiten-
Zaehlung ueber einen KW-Bereich (tage_im_zeitraum), Voll-Wochen-Pruefung fuer
den Auto-Planer (woche_komplett_abwesend) sowie Ueberlappungs-Pruefung beim
Anlegen/Bearbeiten einzelner Abwesenheiten (ueberlappende).

Werktage sind IMMER Montag bis Freitag -- Wochenenden zaehlen nie mit, auch
wenn ein Abwesenheitszeitraum sie umfasst (z. B. Freitag bis Montag)."""

from datetime import date, timedelta

from sqlmodel import Session, select

from app.models.abwesenheit import Abwesenheit
from app.utils.kw import WEEKDAY_LABELS, kw_to_monday

_TYP_NAMEN = {"URLAUB": "Urlaub", "SONSTIGES": "Sonstiges"}


def _werktage_im_bereich(
    von_datum: date, bis_datum: date, range_start: date, range_end: date
) -> set[date]:
    """Menge der Werktage (Mo-Fr), die sowohl in [von_datum, bis_datum] als
    auch in [range_start, range_end] liegen (alle Grenzen inklusive)."""
    start = max(von_datum, range_start)
    end = min(bis_datum, range_end)
    if start > end:
        return set()
    tage: set[date] = set()
    d = start
    while d <= end:
        if d.isoweekday() <= 5:
            tage.add(d)
        d += timedelta(days=1)
    return tage


def _day_span_label(days_sorted: list[int]) -> str:
    """[1, 2, 3] -> "Mo-Mi"; [1] -> "Mo"; [1, 3] -> "Mo, Mi" (Luecke)."""
    if len(days_sorted) == 1:
        return WEEKDAY_LABELS[days_sorted[0]]
    if days_sorted == list(range(days_sorted[0], days_sorted[-1] + 1)):
        return f"{WEEKDAY_LABELS[days_sorted[0]]}-{WEEKDAY_LABELS[days_sorted[-1]]}"
    return ", ".join(WEEKDAY_LABELS[d] for d in days_sorted)


def _tage_wort(anzahl: int) -> str:
    """Korrekter Numerus: 1 -> "1 Tag", sonst "n Tage" (Befund 9)."""
    return "1 Tag" if anzahl == 1 else f"{anzahl} Tage"


def _label(typ_days: dict[str, set[int]], tage: int, voll: bool) -> str:
    """Baut das Tooltip-/Anzeigelabel; kombiniert mehrere Typen in einer
    Woche (sortiert nach dem jeweils fruehesten Wochentag)."""
    segmente = sorted(typ_days.items(), key=lambda kv: min(kv[1]))
    if len(segmente) == 1 and voll:
        typ = segmente[0][0]
        return f"{_TYP_NAMEN.get(typ, typ)} (ganze Woche)"
    teile = [
        f"{_TYP_NAMEN.get(typ, typ)} {_day_span_label(sorted(tage_set))}"
        for typ, tage_set in segmente
    ]
    if voll:
        return f"{', '.join(teile)} (ganze Woche)"
    return f"{', '.join(teile)} ({_tage_wort(tage)})"


def abwesenheit_map(
    db: Session, trainee_ids: list[int], weeks: list[tuple[int, int]]
) -> dict[int, dict[str, dict]]:
    """{trainee_id: {"kw,jahr": {"tage", "voll", "typen", "label"}}} fuer
    alle Wochen mit mindestens einem abwesenden Werktag.

    Laedt die Abwesenheiten ALLER angefragten Trainees fuer den gesamten
    Wochenbereich in EINER Abfrage (kein DB-Zugriff pro Matrix-Zelle).
    Wochen ohne Abwesenheit tauchen im inneren Dict nicht auf; Trainees ganz
    ohne Abwesenheit im Bereich tauchen im aeusseren Dict nicht auf.
    """
    if not trainee_ids or not weeks:
        return {}

    week_bounds: dict[tuple[int, int], tuple[date, date]] = {}
    for kw, jahr in weeks:
        montag = kw_to_monday(kw, jahr)
        week_bounds[(kw, jahr)] = (montag, montag + timedelta(days=4))

    range_start = min(m for m, _ in week_bounds.values())
    range_end = max(f for _, f in week_bounds.values())

    rows = db.exec(
        select(Abwesenheit).where(
            Abwesenheit.trainee_id.in_(trainee_ids),
            Abwesenheit.von_datum <= range_end,
            Abwesenheit.bis_datum >= range_start,
        )
    ).all()

    # trainee_id -> (kw, jahr) -> typ -> {Wochentag-Zahlen 1..5}
    acc: dict[int, dict[tuple[int, int], dict[str, set[int]]]] = {}
    for a in rows:
        typ_wert = a.typ.value if hasattr(a.typ, "value") else str(a.typ)
        for (kw, jahr), (montag, freitag) in week_bounds.items():
            werktage = _werktage_im_bereich(a.von_datum, a.bis_datum, montag, freitag)
            if not werktage:
                continue
            wochentage = {d.isoweekday() for d in werktage}
            (
                acc.setdefault(a.trainee_id, {})
                .setdefault((kw, jahr), {})
                .setdefault(typ_wert, set())
                .update(wochentage)
            )

    result: dict[int, dict[str, dict]] = {}
    for trainee_id, week_map in acc.items():
        result[trainee_id] = {}
        for (kw, jahr), typ_days in week_map.items():
            alle_tage: set[int] = set()
            for tage_set in typ_days.values():
                alle_tage |= tage_set
            anzahl = len(alle_tage)
            voll = anzahl == 5
            result[trainee_id][f"{kw},{jahr}"] = {
                "tage": anzahl,
                "voll": voll,
                "typen": sorted(typ_days.keys()),
                "label": _label(typ_days, anzahl, voll),
            }
    return result


def tage_im_zeitraum(
    db: Session,
    trainee_id: int,
    kw_von: int,
    jahr_von: int,
    kw_bis: int,
    jahr_bis: int,
    typ: str | None = None,
    exclude_days: set[date] | None = None,
) -> int:
    """Anzahl abwesender WERKTAGE (Mo-Fr) im KW-Bereich [kw_von/jahr_von ..
    kw_bis/jahr_bis] (beide inklusive), optional gefiltert auf einen Typ.

    Ueberlappende Abwesenheiten desselben Trainees werden nicht doppelt
    gezaehlt (Menge der abwesenden Kalendertage statt Summe der
    Einzelzeitraeume). Funktioniert ueber Jahreswechsel hinweg (z. B.
    KW52/2025 -> KW1/2026), da kw_to_monday ISO-Kalenderwochen direkt in
    Datumswerte umrechnet.

    exclude_days (Befund 6): Menge von Kalendertagen, die trotz Abwesenheit
    NICHT mitgezaehlt werden -- fuer feedback_utils.fehlzeiten_vorbelegung,
    damit ein Werktag, der bereits als Schultag gezaehlt wurde (Urlaub in
    einer Berufsschulwoche), nicht zusaetzlich als Urlaub/Sonstiges zaehlt
    (Schultage haben Vorrang).
    """
    range_start = kw_to_monday(kw_von, jahr_von)
    range_end = kw_to_monday(kw_bis, jahr_bis) + timedelta(days=4)

    rows = db.exec(
        select(Abwesenheit).where(
            Abwesenheit.trainee_id == trainee_id,
            Abwesenheit.von_datum <= range_end,
            Abwesenheit.bis_datum >= range_start,
        )
    ).all()

    tage: set[date] = set()
    for a in rows:
        if typ is not None:
            a_typ = a.typ.value if hasattr(a.typ, "value") else str(a.typ)
            if a_typ != typ:
                continue
        tage |= _werktage_im_bereich(a.von_datum, a.bis_datum, range_start, range_end)
    if exclude_days:
        tage -= exclude_days
    return len(tage)


def woche_komplett_abwesend(db: Session, trainee_id: int, kw: int, jahr: int) -> bool:
    """True, wenn alle 5 Werktage der KW durch (eine oder mehrere)
    Abwesenheiten abgedeckt sind.

    Befund 14: Der Auto-Planer nutzt produktiv NICHT diese Funktion, sondern
    arbeitet batchweise ueber abwesenheit_map() (eine Abfrage fuer viele
    Trainees/Wochen statt einer Abfrage pro Woche). Diese Funktion bleibt
    bewusst als oeffentliche Einzelfall-API erhalten (z. B. fuer punktuelle
    Checks/Tests zu genau einem Trainee/einer Woche) -- fuer mehrere Wochen
    oder Trainees ist abwesenheit_map() vorzuziehen (deutlich weniger
    DB-Zugriffe)."""
    montag = kw_to_monday(kw, jahr)
    freitag = montag + timedelta(days=4)

    rows = db.exec(
        select(Abwesenheit).where(
            Abwesenheit.trainee_id == trainee_id,
            Abwesenheit.von_datum <= freitag,
            Abwesenheit.bis_datum >= montag,
        )
    ).all()

    tage: set[date] = set()
    for a in rows:
        tage |= _werktage_im_bereich(a.von_datum, a.bis_datum, montag, freitag)
    return len(tage) == 5


def ueberlappende(
    db: Session,
    trainee_id: int,
    von_datum: date,
    bis_datum: date,
    exclude_id: int | None = None,
) -> list[Abwesenheit]:
    """Bestehende Abwesenheiten desselben Trainees, deren Zeitraum sich mit
    [von_datum, bis_datum] ueberschneidet (fuer Anlegen/Bearbeiten:
    exclude_id blendet den gerade bearbeiteten Eintrag selbst aus)."""
    rows = db.exec(
        select(Abwesenheit).where(
            Abwesenheit.trainee_id == trainee_id,
            Abwesenheit.von_datum <= bis_datum,
            Abwesenheit.bis_datum >= von_datum,
        )
    ).all()
    if exclude_id is not None:
        rows = [a for a in rows if a.id != exclude_id]
    return list(rows)
