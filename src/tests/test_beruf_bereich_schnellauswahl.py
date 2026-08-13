"""Tests fuer TEIL 2: Schnellauswahl "Nur IT" / "Nur kaufmaennisch" bei den
Beruf-Checkboxen im Betreuer- (ausbilder_verwaltung/form.html) und im
Abteilungs-Formular (departments/form.html).

(a) membership_utils.beruf_bereich_map leitet je Beruf-Token den Bereich ab
    (Mehrheitsregel wie beruf_art_map, Gleichstand -> "IT"; seit TEIL D
    zusaetzlich der dritte Wert "BEIDE").
(b) Beide Formulare rendern die zwei neuen Buttons sowie das data-bereich-
    Attribut je Checkbox, damit das (unveraenderte) JS-Muster der bereits
    vorhandenen Buttons sie auswerten kann.
(c) TEIL D: ein "BEIDE"-Beruf wird von BEIDEN Buttons ("Nur IT" und "Nur
    kaufmaennisch") angehakt, da er zu beiden Bereichen gehoert.
"""
from sqlmodel import Session, select

from app.models import TraineeClass, UnterrichtsTyp
from app.services.membership_utils import beruf_bereich_map


def _add_class(session: Session, name: str, bereich: str = "IT") -> TraineeClass:
    c = TraineeClass(
        name=name, berufsschule="JD Schule",
        unterrichts_typ=UnterrichtsTyp.BLOCK_FEST, bereich=bereich,
    )
    session.add(c)
    session.commit()
    return c


# ── (a) beruf_bereich_map ──────────────────────────────────────────────────

def test_beruf_bereich_map_it(session: Session):
    _add_class(session, "FISI 1. LJ", bereich="IT")
    _add_class(session, "FIAE 1. LJ", bereich="IT")
    classes = session.exec(select(TraineeClass)).all()
    mapping = beruf_bereich_map(classes)
    assert mapping["FISI"] == "IT"
    assert mapping["FIAE"] == "IT"


def test_beruf_bereich_map_kaufmaennisch(session: Session):
    _add_class(session, "Büro 1. LJ", bereich="KAUFMAENNISCH")
    _add_class(session, "BWL 1. LJ", bereich="KAUFMAENNISCH")
    classes = session.exec(select(TraineeClass)).all()
    mapping = beruf_bereich_map(classes)
    assert mapping["Büro"] == "KAUFMAENNISCH"
    assert mapping["BWL"] == "KAUFMAENNISCH"


def test_beruf_bereich_map_mehrheitsregel(session: Session):
    _add_class(session, "MIX 1. LJ", bereich="KAUFMAENNISCH")
    _add_class(session, "MIX 2. LJ", bereich="KAUFMAENNISCH")
    _add_class(session, "MIX 3. LJ", bereich="IT")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_bereich_map(classes)["MIX"] == "KAUFMAENNISCH"


def test_beruf_bereich_map_gleichstand_gewinnt_it(session: Session):
    _add_class(session, "TIE 1. LJ", bereich="IT")
    _add_class(session, "TIE 2. LJ", bereich="KAUFMAENNISCH")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_bereich_map(classes)["TIE"] == "IT"


# ── (a) TEIL D: dritter Wert "BEIDE" ────────────────────────────────────────

def test_beruf_bereich_map_beide_einheitlich(session: Session):
    """Sind ALLE Klassen eines Berufs explizit 'BEIDE', gilt das eindeutig."""
    _add_class(session, "WI 1. LJ", bereich="BEIDE")
    _add_class(session, "WI 2. LJ", bereich="BEIDE")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_bereich_map(classes)["WI"] == "BEIDE"


def test_beruf_bereich_map_beide_schlaegt_reine_it_kfm_mehrheit(session: Session):
    """'BEIDE' gewinnt, sobald es mindestens so haeufig vorkommt wie IT bzw.
    KAUFMAENNISCH je fuer sich -- hier 1x BEIDE gegen je 1x IT/KAUFMAENNISCH."""
    _add_class(session, "WI 1. LJ", bereich="IT")
    _add_class(session, "WI 2. LJ", bereich="KAUFMAENNISCH")
    _add_class(session, "WI 3. LJ", bereich="BEIDE")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_bereich_map(classes)["WI"] == "BEIDE"


def test_beruf_bereich_map_beide_unterlegen_verliert_gegen_it_mehrheit(session: Session):
    """Ein einzelner 'BEIDE'-Ausreisser gegen eine klare IT-Mehrheit gewinnt
    NICHT -- die Mehrheitsregel bleibt bestehen."""
    _add_class(session, "WI 1. LJ", bereich="IT")
    _add_class(session, "WI 2. LJ", bereich="IT")
    _add_class(session, "WI 3. LJ", bereich="IT")
    _add_class(session, "WI 4. LJ", bereich="BEIDE")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_bereich_map(classes)["WI"] == "IT"


# ── (b) Betreuer-Formular (ausbilder_verwaltung) ───────────────────────────

def test_betreuer_formular_zeigt_bereich_buttons_und_data_attribut(client, session: Session):
    _add_class(session, "FISI 1. LJ", bereich="IT")
    _add_class(session, "Büro 1. LJ", bereich="KAUFMAENNISCH")

    r = client.get("/ausbilder-verwaltung/neu")
    assert r.status_code == 200
    assert "berufAuswahl('it')" in r.text
    assert "berufAuswahl('kaufmaennisch')" in r.text
    assert "Nur IT" in r.text
    assert "Nur kaufmännisch" in r.text
    assert 'data-bereich="IT"' in r.text
    assert 'data-bereich="KAUFMAENNISCH"' in r.text
    assert "cb.dataset.bereich === 'IT'" in r.text
    assert "cb.dataset.bereich === 'KAUFMAENNISCH'" in r.text


# ── (b) Abteilungs-Formular (departments) ───────────────────────────────────

def test_abteilungs_formular_zeigt_bereich_buttons_und_data_attribut(client, session: Session):
    _add_class(session, "FISI 1. LJ", bereich="IT")
    _add_class(session, "Büro 1. LJ", bereich="KAUFMAENNISCH")

    r = client.get("/abteilungen/neu")
    assert r.status_code == 200
    assert "berufAuswahl('it')" in r.text
    assert "berufAuswahl('kaufmaennisch')" in r.text
    assert "Nur IT" in r.text
    assert "Nur kaufmännisch" in r.text
    assert 'data-bereich="IT"' in r.text
    assert 'data-bereich="KAUFMAENNISCH"' in r.text


# ── (c) TEIL D: BEIDE-Beruf wird von beiden Buttons angehakt ───────────────

def test_betreuer_formular_beide_beruf_data_attribut_und_js_deckt_beide_buttons_ab(client, session: Session):
    """Ein Beruf mit bereich='BEIDE' bekommt data-bereich="BEIDE"; das JS
    beider Buttons ('it' UND 'kaufmaennisch') muss diesen Wert zusaetzlich
    zu seinem eigentlichen Bereich abdecken, s. berufAuswahl() im Template."""
    _add_class(session, "WI 1. LJ", bereich="BEIDE")

    r = client.get("/ausbilder-verwaltung/neu")
    assert r.status_code == 200
    assert 'data-bereich="BEIDE"' in r.text
    assert "cb.dataset.bereich === 'IT' || cb.dataset.bereich === 'BEIDE'" in r.text
    assert "cb.dataset.bereich === 'KAUFMAENNISCH' || cb.dataset.bereich === 'BEIDE'" in r.text


def test_abteilungs_formular_beide_beruf_data_attribut_und_js_deckt_beide_buttons_ab(client, session: Session):
    _add_class(session, "WI 1. LJ", bereich="BEIDE")

    r = client.get("/abteilungen/neu")
    assert r.status_code == 200
    assert 'data-bereich="BEIDE"' in r.text
    assert "cb.dataset.bereich === 'IT' || cb.dataset.bereich === 'BEIDE'" in r.text
    assert "cb.dataset.bereich === 'KAUFMAENNISCH' || cb.dataset.bereich === 'BEIDE'" in r.text
