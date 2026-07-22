"""Tests fuer Datenexport/-import (Admin, /daten/).

(a) Export liefert ein ZIP (Magic-Bytes PK) mit allen 12 CSV-Dateien;
    trainees.csv enthaelt einen angelegten Trainee.
(b) Roundtrip: Datensatz quer durch alle Tabellen -> Export -> zusaetzlicher
    Stoer-Datensatz -> Import desselben ZIP -> Stoer-Datensatz weg, alle
    urspruenglichen Objekte mit identischen IDs/Werten wieder da (inkl. Enum,
    next_class_id, date).
(c) Import ohne Bestaetigung -> keine Aenderung.
(d) Kaputte CSV -> Fehler-Redirect UND unveraenderte Daten (Rollback).
(e) orga auf /daten/ -> 403.
"""
import csv
import io
import zipfile
from datetime import date

from sqlmodel import Session

from app.config import settings
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    DepartmentKategorie,
    EinsatzVorschlag,
    SchoolHoliday,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeRolle,
    TraineeWish,
    UnterrichtsTyp,
)

SY = "2025-2026"

ERWARTETE_DATEIEN = {
    "schoolyears.csv", "klassen.csv", "abteilungskategorien.csv",
    "abteilungen.csv", "trainees.csv", "schulplaene.csv",
    "schulplan_wochen.csv", "ferien.csv", "einsaetze.csv",
    "memberships.csv", "wuensche.csv", "vorschlaege.csv",
}


def _login(client, monkeypatch, rolle: str) -> None:
    monkeypatch.setattr(settings, "auth_mode", "dev")
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303


def _build_full_dataset(session: Session) -> dict:
    """Legt quer durch ALLE Registry-Tabellen je einen Datensatz an."""
    sy = Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026, archiviert=False)
    session.add(sy)

    k1 = TraineeClass(name="RT 1. LJ", berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(k1)
    session.flush()
    k2 = TraineeClass(name="RT 2. LJ", berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(k2)
    session.flush()
    k1.next_class_id = k2.id  # Self-FK
    session.add(k1)

    kat = DepartmentKategorie(name="RT-Kategorie")
    session.add(kat)
    session.flush()
    dept = Department(code="RT", name="Roundtrip-Abteilung", kategorie_id=kat.id, farbe="#123456")
    session.add(dept)
    session.flush()

    trainee = Trainee(
        vorname="Rita", nachname="Roundtrip", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1), upn="rita.roundtrip@grenke.de",
    )
    session.add(trainee)
    session.flush()

    plan = SchoolPlan(klasse_id=k1.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()
    week = SchoolPlanWeek(plan_id=plan.id, kw=10, jahr=2026, typ=SchoolWeekTyp.BERUFSSCHULE)
    session.add(week)

    holiday = SchoolHoliday(
        schoolyear_id=SY, name="Osterferien", start_kw=13, start_year=2026, end_kw=14, end_year=2026,
    )
    session.add(holiday)

    assignment = Assignment(
        trainee_id=trainee.id, schoolyear_id=SY, kw=20, jahr=2026,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id, source=AssignmentSource.MANUAL,
        bestaetigung="bestaetigt", feedback="Sehr gut gemacht",
    )
    session.add(assignment)

    membership = TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY, klasse_id=k1.id)
    session.add(membership)

    wish = TraineeWish(trainee_id=trainee.id, department_id=dept.id, prioritaet=1)
    session.add(wish)

    vorschlag = EinsatzVorschlag(
        trainee_id=trainee.id, department_id=dept.id, schoolyear_id=SY,
        kw_von=5, jahr_von=2026, kw_bis=8, jahr_bis=2026,
        kommentar="Bitte Cloud-Team", eingereicht_von_upn="rita.roundtrip@grenke.de",
        eingereicht_von_name="Rita Roundtrip", status="offen", erstellt_am=date(2025, 12, 1),
    )
    session.add(vorschlag)

    session.commit()

    return {
        "sy_id": sy.id,
        "k1_id": k1.id, "k2_id": k2.id,
        "kat_id": kat.id, "dept_id": dept.id,
        "trainee_id": trainee.id,
        "plan_id": plan.id, "week_id": week.id,
        "holiday_id": holiday.id, "assignment_id": assignment.id,
        "membership_id": membership.id, "wish_id": wish.id,
        "vorschlag_id": vorschlag.id,
    }


# ── (a) Export ─────────────────────────────────────────────────────────────

def test_export_liefert_zip_mit_allen_tabellen(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")

    t = Trainee(vorname="Erika", nachname="Export", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get("/daten/export")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
    assert r.headers["content-type"].startswith("application/zip")
    assert "attachment" in r.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert ERWARTETE_DATEIEN <= set(zf.namelist())

    trainees_csv = zf.read("trainees.csv").decode("utf-8-sig")
    assert "Erika" in trainees_csv
    assert "Export" in trainees_csv


# ── (e) Rollen-Guard ───────────────────────────────────────────────────────

def test_orga_darf_nicht_auf_daten_index(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.get("/daten/", follow_redirects=False)
    assert r.status_code == 403


def test_orga_darf_nicht_exportieren(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.get("/daten/export", follow_redirects=False)
    assert r.status_code == 403


def test_orga_darf_nicht_importieren(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.post(
        "/daten/import",
        data={"bestaetigt": "1"},
        files={"zip_datei": ("x.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip")},
        follow_redirects=False,
    )
    assert r.status_code == 403


# ── (b) Roundtrip ──────────────────────────────────────────────────────────

def test_roundtrip_export_dann_import_stellt_identische_daten_wieder_her(
    client, session: Session, monkeypatch,
):
    _login(client, monkeypatch, "admin")
    ids = _build_full_dataset(session)

    r = client.get("/daten/export")
    assert r.status_code == 200
    zip_bytes = r.content

    # Stoer-Datensatz zusaetzlich anlegen (soll nach Import wieder weg sein)
    stoer = Trainee(vorname="Stoer", nachname="Faktor", rolle=TraineeRolle.AZUBI)
    session.add(stoer)
    session.commit()
    stoer_id = stoer.id

    r = client.post(
        "/daten/import",
        data={"bestaetigt": "1"},
        files={"zip_datei": ("export.zip", zip_bytes, "application/zip")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]

    session.expire_all()

    # Stoer-Datensatz ist weg
    assert session.get(Trainee, stoer_id) is None

    sy = session.get(Schoolyear, ids["sy_id"])
    assert sy is not None
    assert sy.start_year == 2025
    assert sy.archiviert is False

    k1 = session.get(TraineeClass, ids["k1_id"])
    k2 = session.get(TraineeClass, ids["k2_id"])
    assert k1 is not None and k2 is not None
    assert k1.next_class_id == k2.id  # Self-FK korrekt wiederhergestellt

    kat = session.get(DepartmentKategorie, ids["kat_id"])
    dept = session.get(Department, ids["dept_id"])
    assert kat is not None and dept is not None
    assert dept.kategorie_id == kat.id
    assert dept.farbe == "#123456"

    trainee = session.get(Trainee, ids["trainee_id"])
    assert trainee is not None
    assert trainee.vorname == "Rita"
    assert trainee.nachname == "Roundtrip"
    assert trainee.klasse_id == k1.id
    assert trainee.ausbildungsbeginn == date(2025, 9, 1)
    assert trainee.upn == "rita.roundtrip@grenke.de"

    plan = session.get(SchoolPlan, ids["plan_id"])
    week = session.get(SchoolPlanWeek, ids["week_id"])
    assert plan is not None and week is not None
    assert week.plan_id == plan.id
    assert week.typ == SchoolWeekTyp.BERUFSSCHULE

    holiday = session.get(SchoolHoliday, ids["holiday_id"])
    assert holiday is not None
    assert holiday.name == "Osterferien"

    assignment = session.get(Assignment, ids["assignment_id"])
    assert assignment is not None
    assert assignment.typ == AssignmentTyp.ABTEILUNG
    assert assignment.source == AssignmentSource.MANUAL
    assert assignment.bestaetigung == "bestaetigt"
    assert assignment.feedback == "Sehr gut gemacht"

    membership = session.get(TraineeClassMembership, ids["membership_id"])
    assert membership is not None
    assert membership.klasse_id == k1.id

    wish = session.get(TraineeWish, ids["wish_id"])
    assert wish is not None
    assert wish.prioritaet == 1

    vorschlag = session.get(EinsatzVorschlag, ids["vorschlag_id"])
    assert vorschlag is not None
    assert vorschlag.status == "offen"
    assert vorschlag.erstellt_am == date(2025, 12, 1)
    assert vorschlag.kommentar == "Bitte Cloud-Team"


# ── (c) Import ohne Bestaetigung ────────────────────────────────────────────

def test_import_ohne_bestaetigung_aendert_nichts(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")
    ids = _build_full_dataset(session)

    r = client.get("/daten/export")
    zip_bytes = r.content

    extra = Trainee(vorname="Bleibt", nachname="Erhalten", rolle=TraineeRolle.AZUBI)
    session.add(extra)
    session.commit()
    extra_id = extra.id

    r = client.post(
        "/daten/import",
        data={},  # keine bestaetigt-Checkbox
        files={"zip_datei": ("export.zip", zip_bytes, "application/zip")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]

    session.expire_all()
    # Nichts geloescht, nichts veraendert
    assert session.get(Trainee, extra_id) is not None
    assert session.get(Trainee, ids["trainee_id"]) is not None


# ── (d) Kaputte CSV -> Rollback ──────────────────────────────────────────────

def test_import_kaputte_csv_rollback(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")
    ids = _build_full_dataset(session)

    r = client.get("/daten/export")
    original_zip = zipfile.ZipFile(io.BytesIO(r.content))

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in original_zip.namelist():
            raw = original_zip.read(name)
            if name == "trainees.csv":
                text = raw.decode("utf-8-sig")
                rows = list(csv.reader(io.StringIO(text)))
                header = rows[0]
                idx = header.index("klasse_id")
                rows[1][idx] = "NICHT_NUMERISCH"  # kaputt: Text statt int
                buf = io.StringIO()
                csv.writer(buf).writerows(rows)
                raw = buf.getvalue().encode("utf-8-sig")
            zf.writestr(name, raw)
    kaputtes_zip = out.getvalue()

    r = client.post(
        "/daten/import",
        data={"bestaetigt": "1"},
        files={"zip_datei": ("kaputt.zip", kaputtes_zip, "application/zip")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]

    # Urspruengliche Daten unveraendert (Rollback!)
    session.expire_all()
    trainee = session.get(Trainee, ids["trainee_id"])
    assert trainee is not None
    assert trainee.vorname == "Rita"
    assert trainee.klasse_id == ids["k1_id"]

    k1 = session.get(TraineeClass, ids["k1_id"])
    assert k1 is not None
    assert k1.next_class_id == ids["k2_id"]

    sy = session.get(Schoolyear, ids["sy_id"])
    assert sy is not None
