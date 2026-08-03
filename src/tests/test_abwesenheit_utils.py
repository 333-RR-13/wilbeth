"""Tests fuer app.services.abwesenheit_utils (Wochen-Overlay fuer die
Einsatzmatrix, Fehlzeiten-Zaehlung, Voll-Wochen-Pruefung, Ueberlappung)."""

from datetime import date

from app.models import (
    Abwesenheit,
    AbwesenheitQuelle,
    AbwesenheitTyp,
    Trainee,
    TraineeRolle,
)
from app.services.abwesenheit_utils import (
    abwesenheit_map,
    tage_im_zeitraum,
    ueberlappende,
    woche_komplett_abwesend,
)


def _make_trainee(session, vorname="Jonas", nachname="Jaeger") -> int:
    t = Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t.id


def _make_abwesenheit(
    session,
    trainee_id: int,
    von_datum: date,
    bis_datum: date,
    typ: AbwesenheitTyp = AbwesenheitTyp.URLAUB,
    quelle: AbwesenheitQuelle = AbwesenheitQuelle.SELBST,
) -> Abwesenheit:
    a = Abwesenheit(
        trainee_id=trainee_id, von_datum=von_datum, bis_datum=bis_datum,
        typ=typ, quelle=quelle,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


# ── abwesenheit_map ──────────────────────────────────────────────────────

def test_abwesenheit_map_teilwoche_mo_bis_mi(session):
    t = _make_trainee(session)
    # KW 10/2026: Montag 2026-03-02 .. Freitag 2026-03-06
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 4))

    result = abwesenheit_map(session, [t], [(10, 2026)])

    eintrag = result[t]["10,2026"]
    assert eintrag["tage"] == 3
    assert eintrag["voll"] is False
    assert eintrag["typen"] == ["URLAUB"]
    assert eintrag["label"] == "Urlaub Mo-Mi (3 Tage)"


def test_abwesenheit_map_label_singular_ein_tag(session):
    """Befund 9: Numerus -- "1 Tag" statt faelschlich "1 Tage"."""
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 6), date(2026, 3, 6))  # nur Freitag

    result = abwesenheit_map(session, [t], [(10, 2026)])

    eintrag = result[t]["10,2026"]
    assert eintrag["tage"] == 1
    assert eintrag["label"] == "Urlaub Fr (1 Tag)"


def test_abwesenheit_map_ganze_woche(session):
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 6))

    result = abwesenheit_map(session, [t], [(10, 2026)])

    eintrag = result[t]["10,2026"]
    assert eintrag["tage"] == 5
    assert eintrag["voll"] is True
    assert eintrag["label"] == "Urlaub (ganze Woche)"


def test_abwesenheit_map_wochenende_faellt_raus(session):
    t = _make_trainee(session)
    # Freitag 2026-03-06 (KW10) bis Montag 2026-03-09 (KW11) -> nur Fr + Mo zaehlen
    _make_abwesenheit(session, t, date(2026, 3, 6), date(2026, 3, 9))

    result = abwesenheit_map(session, [t], [(10, 2026), (11, 2026)])

    assert result[t]["10,2026"]["tage"] == 1
    assert result[t]["11,2026"]["tage"] == 1


def test_abwesenheit_map_ueber_mehrere_wochen(session):
    t = _make_trainee(session)
    # KW10 (Mo 2026-03-02 .. Fr 2026-03-06) + KW11 (Mo 2026-03-09 .. Fr 2026-03-13)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 13))

    result = abwesenheit_map(session, [t], [(10, 2026), (11, 2026)])

    assert result[t]["10,2026"]["voll"] is True
    assert result[t]["11,2026"]["voll"] is True


def test_abwesenheit_map_zwei_typen_in_einer_woche(session):
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 3), typ=AbwesenheitTyp.URLAUB)
    _make_abwesenheit(
        session, t, date(2026, 3, 4), date(2026, 3, 6), typ=AbwesenheitTyp.SONSTIGES
    )

    result = abwesenheit_map(session, [t], [(10, 2026)])

    eintrag = result[t]["10,2026"]
    assert eintrag["tage"] == 5
    assert eintrag["voll"] is True
    assert set(eintrag["typen"]) == {"URLAUB", "SONSTIGES"}
    assert eintrag["label"] == "Urlaub Mo-Di, Sonstiges Mi-Fr (ganze Woche)"


def test_abwesenheit_map_woche_ohne_abwesenheit_fehlt_im_dict(session):
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 4))

    result = abwesenheit_map(session, [t], [(10, 2026), (11, 2026)])

    assert "11,2026" not in result[t]


def test_abwesenheit_map_trainee_ohne_abwesenheit_fehlt_komplett(session):
    t1 = _make_trainee(session, "Jonas", "Jaeger")
    t2 = _make_trainee(session, "Anna", "Schmidt")
    _make_abwesenheit(session, t1, date(2026, 3, 2), date(2026, 3, 4))

    result = abwesenheit_map(session, [t1, t2], [(10, 2026)])

    assert t1 in result
    assert t2 not in result


# ── tage_im_zeitraum ─────────────────────────────────────────────────────

def test_tage_im_zeitraum_ueber_kw_bereich(session):
    t = _make_trainee(session)
    # KW10 komplett (5 Tage) + KW11 Mo-Di (2 Tage) = 7 Tage
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 10))

    assert tage_im_zeitraum(session, t, 10, 2026, 11, 2026) == 7


def test_tage_im_zeitraum_ueber_jahreswechsel_kw52_kw1(session):
    t = _make_trainee(session)
    # ISO KW52/2025: Mo 2025-12-22 .. Fr 2025-12-26
    # ISO KW1/2026:  Mo 2025-12-29 .. Fr 2026-01-02
    _make_abwesenheit(session, t, date(2025, 12, 22), date(2026, 1, 2))

    assert tage_im_zeitraum(session, t, 52, 2025, 1, 2026) == 10


def test_tage_im_zeitraum_exclude_days_zieht_tage_ab(session):
    """Befund 6 (Grundlage): exclude_days blendet einzelne Kalendertage aus
    der Zaehlung aus -- Basis dafuer, dass feedback_utils.fehlzeiten_vorbelegung
    Schultage nicht zusaetzlich als Urlaub zaehlt."""
    t = _make_trainee(session)
    # KW10 komplett (Mo 2026-03-02 .. Fr 2026-03-06)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 6))

    ohne_exclude = tage_im_zeitraum(session, t, 10, 2026, 10, 2026)
    mit_exclude = tage_im_zeitraum(
        session, t, 10, 2026, 10, 2026,
        exclude_days={date(2026, 3, 2), date(2026, 3, 3)},
    )

    assert ohne_exclude == 5
    assert mit_exclude == 3


def test_tage_im_zeitraum_mit_typ_filter(session):
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 3), typ=AbwesenheitTyp.URLAUB)
    _make_abwesenheit(
        session, t, date(2026, 3, 4), date(2026, 3, 6), typ=AbwesenheitTyp.SONSTIGES
    )

    assert tage_im_zeitraum(session, t, 10, 2026, 10, 2026) == 5
    assert tage_im_zeitraum(session, t, 10, 2026, 10, 2026, typ="URLAUB") == 2
    assert tage_im_zeitraum(session, t, 10, 2026, 10, 2026, typ="SONSTIGES") == 3


# ── woche_komplett_abwesend ──────────────────────────────────────────────

def test_woche_komplett_abwesend_true_bei_voller_woche(session):
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 6))

    assert woche_komplett_abwesend(session, t, 10, 2026) is True


def test_woche_komplett_abwesend_false_bei_teilwoche(session):
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 4))

    assert woche_komplett_abwesend(session, t, 10, 2026) is False


def test_woche_komplett_abwesend_kombiniert_zwei_eintraege(session):
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 3), typ=AbwesenheitTyp.URLAUB)
    _make_abwesenheit(
        session, t, date(2026, 3, 4), date(2026, 3, 6), typ=AbwesenheitTyp.SONSTIGES
    )

    assert woche_komplett_abwesend(session, t, 10, 2026) is True


# ── ueberlappende ────────────────────────────────────────────────────────

def test_ueberlappende_findet_ueberschneidung(session):
    t = _make_trainee(session)
    a = _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 6))

    treffer = ueberlappende(session, t, date(2026, 3, 4), date(2026, 3, 10))

    assert [x.id for x in treffer] == [a.id]


def test_ueberlappende_kein_treffer_ohne_ueberschneidung(session):
    t = _make_trainee(session)
    _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 6))

    treffer = ueberlappende(session, t, date(2026, 3, 9), date(2026, 3, 13))

    assert treffer == []


def test_ueberlappende_exclude_id_blendet_eigenen_eintrag_aus(session):
    t = _make_trainee(session)
    a = _make_abwesenheit(session, t, date(2026, 3, 2), date(2026, 3, 6))

    treffer = ueberlappende(session, t, date(2026, 3, 2), date(2026, 3, 6), exclude_id=a.id)

    assert treffer == []
