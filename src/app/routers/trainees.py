import urllib.parse
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Assignment,
    BetreuerTrainee,
    Department,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeNotiz,
    TraineeRolle,
    TraineeWish,
)
from app.models.trainee_wish import group_wishes_by_priority, prioritaet_label
from app.models.betreuer import FUNKTION_LABELS
from app.services.auth_service import CurrentUser, allowed_dept_ids, require_roles
from app.services.betreuung_utils import betreuer_fuer_trainee
from app.services.conflict_checker import find_conflicts
from app.services.dept_history import visited_department_ids
from app.services.membership_utils import (
    aktuelles_schuljahr_id,
    beruf_art_map,
    beruf_langname,
    beruf_optionen,
    beruf_und_lehrjahr,
    einstiegsklasse_fuer_beruf,
    klasse_fuer,
    semester_label,
    upsert_membership,
)
from app.services.school_sync import sync_trainee
from app.services.trainee_notiz_service import darf_notiz_anlegen, erstelle_notiz
from app.utils.colors import department_color_map

router = APIRouter(prefix="/trainees", tags=["trainees"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
templates.env.globals["prioritaet_label"] = prioritaet_label
templates.env.globals["FUNKTION_LABELS"] = FUNKTION_LABELS
DB = Annotated[Session, Depends(get_session)]


def _parse_ausbildungsbeginn(raw: str) -> tuple[date | None, str | None]:
    """Parst das Pflichtfeld Ausbildungsbeginn.

    Rueckgabe (wert, fehlertext); bei Erfolg ist fehlertext None.
    """
    if not raw:
        return None, "Ausbildungsbeginn ist Pflicht"
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return None, "Ausbildungsbeginn ist ungueltig"


_MONATSNAMEN = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)

# Uebliche Startmonate: Regelfall 01.09., Ausnahme 01.01. des Folgejahres
# (verkuerzte Ausbildung); 08 und 10 als Puffer fuer leicht abweichende
# Starttermine um den Regelfall herum.
_UEBLICHE_STARTMONATE = (1, 8, 9, 10)


def _ausbildungsbeginn_warnung(beginn: date) -> str | None:
    """Liefert einen Warnhinweis, wenn der Ausbildungsbeginn unplausibel wirkt.

    Kein Block - Ausnahmen kommen vor (Wiederholer, Quereinsteiger etc.).
    Plausibel ist nur ein Datum, das SOWOHL auf den 1. eines Monats faellt
    ALS AUCH in einem der ueblichen Startmonate liegt; alles andere (z. B.
    ein Tippfehler wie 9. Januar statt 1. September durch ein Browser-Datumsfeld
    im MM/DD/YYYY-Format) bekommt einen Hinweis zum Nachpruefen.
    """
    if beginn.day == 1 and beginn.month in _UEBLICHE_STARTMONATE:
        return None
    monatsname = _MONATSNAMEN[beginn.month - 1]
    return (
        f"Ungewöhnlicher Ausbildungsbeginn: {beginn.day}. {monatsname} {beginn.year} "
        "– bitte prüfen, ob das Datum stimmt."
    )


_ROLLE_ART_LABEL: dict[TraineeRolle, str] = {
    TraineeRolle.AZUBI: "Azubi",
    TraineeRolle.DH_STUDENT: "DH-Student",
}


def _rolle_art_warnung(rolle: TraineeRolle, art: str) -> str | None:
    """Warnung, wenn die Art der gewaehlten Klasse (Ausbildung/Studium) nicht
    zur Rolle passt (AZUBI erwartet AUSBILDUNG, DH_STUDENT erwartet STUDIUM).

    Kein Block - Ausnahmen kommen vor (z. B. Quereinsteiger, Sonderfaelle).
    PRAKTIKANT/UMSCHUELER duerfen jede Art waehlen -> nie eine Warnung.
    """
    erwartet = {TraineeRolle.AZUBI: "AUSBILDUNG", TraineeRolle.DH_STUDENT: "STUDIUM"}.get(rolle)
    if erwartet is None or art == erwartet:
        return None
    art_label = "einen Studiengang" if art == "STUDIUM" else "einen Ausbildungsberuf"
    return (
        f"{_ROLLE_ART_LABEL[rolle]} mit {art_label} ausgewählt "
        "– bitte prüfen, ob das stimmt."
    )


def _resolve_einstiegsklasse_id(
    db: Session, sonderfall: str, klasse_id: str, beruf: str,
) -> tuple[int | None, str | None]:
    """Ermittelt die Einstiegsklasse (Anker) aus Sonderfall- oder Beruf-Eingabe.

    Sonderfall gesetzt -> klasse_id ist Pflicht (direkte Klassenwahl).
    Sonst -> beruf ist Pflicht; die Einstiegsklasse wird ueber
    einstiegsklasse_fuer_beruf() abgeleitet ("<Beruf> 1. LJ" bzw. DH-Kohorte).

    Rueckgabe (klasse_id, fehlertext); bei Erfolg ist fehlertext None.
    """
    if sonderfall:
        if not klasse_id:
            return None, "Bei Sonderfall ist eine Klasse Pflicht"
        return int(klasse_id), None
    if not beruf:
        return None, "Ausbildungsberuf ist Pflicht"
    all_classes = list(db.exec(select(TraineeClass)).all())
    klasse = einstiegsklasse_fuer_beruf(all_classes, beruf)
    if klasse is None:
        return None, f"Keine Klasse '{beruf} 1. LJ' vorhanden"
    return klasse.id, None


@router.get("/", response_class=HTMLResponse)
def list_trainees(
    request: Request, db: DB, status: str = "aktiv",
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Liste der Trainees mit Status-Filter: aktiv | archiviert | alle."""
    q = select(Trainee).order_by(Trainee.nachname, Trainee.vorname)
    if status == "aktiv":
        q = q.where(Trainee.aktiv == True)  # noqa: E712
    elif status == "archiviert":
        q = q.where(Trainee.aktiv == False)  # noqa: E712
    # status == "alle": kein Filter
    trainees = db.exec(q).all()
    classes = {c.id: c for c in db.exec(select(TraineeClass)).all()}

    # BERECHNETE Klasse fuers laufende Jahr anzeigen (konsistent mit Uebersicht
    # und Jahresabschluss) - die rohe Einstiegsklasse ist nur der Anker und
    # wuerde falsche Anker-Daten verstecken.
    anzeige_jahr = aktuelles_schuljahr_id(db)
    klasse_map: dict[int, TraineeClass | None] = {}
    for t in trainees:
        kid = klasse_fuer(db, t, anzeige_jahr) if anzeige_jahr else t.klasse_id
        klasse_map[t.id] = classes.get(kid) if kid else None

    # Trainees, deren angezeigte Klasse fuers anzeige_jahr aus einem Override
    # (statt der Berechnung) stammt - fuers "Ausnahme"-Badge.
    override_ids: set[int] = set()
    if anzeige_jahr:
        override_ids = {
            m.trainee_id
            for m in db.exec(
                select(TraineeClassMembership).where(
                    TraineeClassMembership.schoolyear_id == anzeige_jahr,
                )
            ).all()
        }

    return templates.TemplateResponse(request, "trainees/list.html", {
        "trainees": trainees,
        "classes": classes,
        "klasse_map": klasse_map,
        "anzeige_jahr": anzeige_jahr,
        "override_ids": override_ids,
        "active_nav": "trainees",
        "status": status,
    })


@router.get("/upn-pflege", response_class=HTMLResponse)
def upn_pflege(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Sammel-Pflege der UPN (Entra-Anmeldename) fuer alle aktiven Trainees."""
    trainees = db.exec(
        select(Trainee)
        .where(Trainee.aktiv == True)  # noqa: E712
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()
    return templates.TemplateResponse(request, "trainees/upn_pflege.html", {
        "trainees": trainees,
        "active_nav": "trainees",
    })


@router.post("/upn-pflege", response_class=RedirectResponse)
async def upn_pflege_speichern(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Speichert die je Zeile eingetragenen UPN-Werte fuer alle aktiven Trainees."""
    form = await request.form()
    trainees = db.exec(
        select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
    ).all()
    for t in trainees:
        field_name = f"upn_{t.id}"
        if field_name not in form:
            continue
        neuer_wert = (form[field_name] or "").strip() or None
        if neuer_wert != t.upn:
            t.upn = neuer_wert
            db.add(t)
    db.commit()
    return RedirectResponse("/trainees/upn-pflege?msg=updated", status_code=303)


@router.get("/neu", response_class=HTMLResponse)
def new_trainee(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    return templates.TemplateResponse(request, "trainees/form.html", {
        "trainee": None,
        "classes": classes,
        "rollen": list(TraineeRolle),
        "years": years,
        "overrides": [],
        "beruf_optionen": beruf_optionen(classes),
        "beruf_selected": "",
        "beruf_art_map": beruf_art_map(classes),
        "sonderfall_checked": False,
        "active_nav": "trainees",
    })


@router.post("/", response_class=RedirectResponse)
def create_trainee(
    db: DB,
    vorname: Annotated[str, Form()],
    nachname: Annotated[str, Form()],
    rolle: Annotated[TraineeRolle, Form()],
    klasse_id: Annotated[str, Form()] = "",
    beruf: Annotated[str, Form()] = "",
    sonderfall: Annotated[str, Form()] = "",
    membership_year_id: Annotated[str, Form()] = "",
    membership_klasse_id: Annotated[str, Form()] = "",
    steckbrief: Annotated[str, Form()] = "",
    aktiv: Annotated[str, Form()] = "",
    ausbildungsbeginn: Annotated[str, Form()] = "",
    upn: Annotated[str, Form()] = "",
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    ausbildungsbeginn_parsed, err = _parse_ausbildungsbeginn(ausbildungsbeginn)
    if err:
        return RedirectResponse(
            f"/trainees/neu?msg=error&detail={urllib.parse.quote(err)}", status_code=303
        )

    klasse_id_int, err = _resolve_einstiegsklasse_id(db, sonderfall, klasse_id, beruf)
    if err:
        return RedirectResponse(
            f"/trainees/neu?msg=error&detail={urllib.parse.quote(err)}", status_code=303
        )

    t = Trainee(
        vorname=vorname,
        nachname=nachname,
        rolle=rolle,
        klasse_id=klasse_id_int,
        steckbrief=steckbrief,
        aktiv=bool(aktiv),
        ausbildungsbeginn=ausbildungsbeginn_parsed,
        upn=upn.strip() or None,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    # Optionaler Membership-Override fuer ein bestimmtes Schuljahr
    mem_klasse_int = int(membership_klasse_id) if membership_klasse_id else None
    if membership_year_id and mem_klasse_int:
        upsert_membership(db, t.id, membership_year_id, mem_klasse_int)
        db.commit()
    sync_trainee(db, t.id)
    redirect_url = f"/trainees/{t.id}?msg=created"
    warnungen = []
    beginn_warnung = _ausbildungsbeginn_warnung(ausbildungsbeginn_parsed)
    if beginn_warnung:
        warnungen.append(beginn_warnung)
    klasse_fuer_warnung = db.get(TraineeClass, klasse_id_int) if klasse_id_int else None
    art_warnung = _rolle_art_warnung(rolle, klasse_fuer_warnung.art if klasse_fuer_warnung else "AUSBILDUNG")
    if art_warnung:
        warnungen.append(art_warnung)
    if warnungen:
        redirect_url += f"&warnung={urllib.parse.quote(' '.join(warnungen))}"
    return RedirectResponse(redirect_url, status_code=303)


@router.get("/{trainee_id:int}", response_class=HTMLResponse)
def trainee_detail(
    request: Request, trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("ausbilder", "orga", "admin")),
):
    if user.rolle == "ausbilder":
        if not (allowed_dept_ids(db, user) & visited_department_ids(db, trainee_id)):
            raise HTTPException(status_code=403, detail="Keine Berechtigung")
    trainee = db.get(Trainee, trainee_id)
    years_list = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    years = {y.id: y for y in years_list}
    all_depts = db.exec(select(Department)).all()
    depts = {d.id: d for d in all_depts}
    dept_colors = department_color_map(all_depts)
    assignments = db.exec(
        select(Assignment)
        .where(Assignment.trainee_id == trainee_id)
        .order_by(Assignment.jahr, Assignment.kw)
    ).all()

    conflict_cells: set[str] = set()
    for year_id in years:
        for c in find_conflicts(db, year_id):
            if c.trainee_id == trainee_id:
                conflict_cells.add(f"{c.kw}~{c.jahr}")

    _today = date.today().isocalendar()
    today_key = f"{_today.week}~{_today.year}"

    # Wuensche des Trainees (fuer die Planerin sichtbar), gruppiert nach
    # Prioritaet (Muss/Sollte/Kann); order_by(id) = gespeicherte Reihenfolge
    # innerhalb einer Gruppe. Wuensche, die der Trainee bereits (in der
    # Vergangenheit) in genau dieser Abteilung erfuellt hat, werden aus den
    # Prioritaets-Gruppen herausgenommen und separat unter "Bereits erfuellt"
    # gefuehrt (siehe dept_history.visited_department_ids(nur_vergangenheit=True)).
    wishes = db.exec(
        select(TraineeWish)
        .where(TraineeWish.trainee_id == trainee_id)
        .order_by(TraineeWish.id)
    ).all()
    erfuellt_ids = visited_department_ids(db, trainee_id, nur_vergangenheit=True)
    offene_wishes = [w for w in wishes if w.department_id not in erfuellt_ids]
    erfuellte_wishes = [w for w in wishes if w.department_id in erfuellt_ids]
    wish_groups = group_wishes_by_priority([
        (w.prioritaet, depts[w.department_id].code if w.department_id in depts else "?")
        for w in offene_wishes
    ])
    erfuellte_codes = sorted(
        depts[w.department_id].code for w in erfuellte_wishes if w.department_id in depts
    )

    # Notizen der Ausbilder ueber den Trainee (Teil C) -- chronologisch
    # absteigend (neueste zuerst). Wer diese Seite laut obiger Rollen-Pruefung
    # oeffnen darf, sieht ALLE Notizen (auch die anderer Abteilungen).
    notizen = db.exec(
        select(TraineeNotiz)
        .where(TraineeNotiz.trainee_id == trainee_id)
        .order_by(TraineeNotiz.erstellt_am.desc(), TraineeNotiz.id.desc())
    ).all()

    # ── Visitenkarte ────────────────────────────────────────────────
    # Klasse ueber klasse_fuer ermitteln (laufendes Schuljahr = berechneter Anker;
    # NICHT das neueste Jahr - ein bereits angelegtes Folgejahr wuerde sonst
    # kommentarlos die Zukunft zeigen, siehe aktuelles_schuljahr_id()).
    schoolyear_id = aktuelles_schuljahr_id(db) or None
    klasse_id = klasse_fuer(db, trainee, schoolyear_id) if schoolyear_id else trainee.klasse_id
    klasse = db.get(TraineeClass, klasse_id) if klasse_id else None
    # Ausbildungsberuf ausgeschrieben
    beruf_token, lehrjahr = beruf_und_lehrjahr(klasse.name if klasse else None)
    beruf_lang = beruf_langname(beruf_token)
    # Fuer DH-Studenten: Semester-Label ermitteln
    sem_label: str | None = None
    if schoolyear_id and trainee.rolle != TraineeRolle.AZUBI:
        sem_label = semester_label(db, trainee, schoolyear_id, "")

    # Stammt die angezeigte Klasse aus einem Override (statt der Berechnung)?
    ist_override = False
    if schoolyear_id:
        ist_override = db.exec(
            select(TraineeClassMembership).where(
                TraineeClassMembership.trainee_id == trainee_id,
                TraineeClassMembership.schoolyear_id == schoolyear_id,
            )
        ).first() is not None

    # Betreuung (Personen, die den Trainee ueber die gesamte Ausbildung
    # begleiten -- unabhaengig von den abteilungsbezogenen Ausbildern oben).
    betreuer_liste = betreuer_fuer_trainee(db, trainee, schoolyear_id)

    return templates.TemplateResponse(request, "trainees/detail.html", {
        "trainee": trainee,
        "klasse": klasse,
        "ist_override": ist_override,
        "sem_label": sem_label,
        "years": years,
        "depts": depts,
        "dept_colors": dept_colors,
        "assignments": assignments,
        "conflict_cells": conflict_cells,
        "today_key": today_key,
        "wishes": wishes,
        "wish_groups": wish_groups,
        "erfuellte_codes": erfuellte_codes,
        "notizen": notizen,
        "beruf_lang": beruf_lang,
        "ausbildungsbeginn": trainee.ausbildungsbeginn,
        "betreuer_liste": betreuer_liste,
        "active_nav": "trainees",
    })


@router.post("/{trainee_id:int}/notizen", response_class=RedirectResponse)
def create_notiz(
    trainee_id: int, db: DB,
    text: Annotated[str, Form()],
    user: CurrentUser = Depends(require_roles("ausbilder", "orga", "admin")),
):
    """Legt eine Notiz OHNE Einsatz-Kontext an (Profil-Direkteingabe)."""
    if not darf_notiz_anlegen(db, user, trainee_id, department_id=None):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    notiz = erstelle_notiz(db, user, trainee_id, text)
    if notiz is None:
        return RedirectResponse(
            f"/trainees/{trainee_id}?msg=error&detail={urllib.parse.quote('Notiz darf nicht leer sein')}",
            status_code=303,
        )
    return RedirectResponse(f"/trainees/{trainee_id}?msg=created", status_code=303)


@router.post("/{trainee_id:int}/notizen/{notiz_id}/loeschen", response_class=RedirectResponse)
def loeschen_notiz(
    trainee_id: int, notiz_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("ausbilder", "orga", "admin")),
):
    """Loescht eine TraineeNotiz -- nur der Verfasser selbst oder admin."""
    notiz = db.get(TraineeNotiz, notiz_id)
    if notiz is None or notiz.trainee_id != trainee_id:
        raise HTTPException(status_code=404, detail="Notiz nicht gefunden")

    ist_verfasser = user.upn.strip().lower() == (notiz.verfasser_upn or "").strip().lower()
    if not (user.rolle == "admin" or ist_verfasser):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    db.delete(notiz)
    db.commit()
    return RedirectResponse(f"/trainees/{trainee_id}?msg=deleted", status_code=303)


@router.post("/{trainee_id:int}/share-token", response_class=RedirectResponse)
def generate_share_token(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    t = db.get(Trainee, trainee_id)
    t.share_token = str(uuid.uuid4())
    db.commit()
    return RedirectResponse(f"/trainees/{trainee_id}?msg=updated", status_code=303)


@router.post("/{trainee_id:int}/share-token/deaktivieren", response_class=RedirectResponse)
def revoke_share_token(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    t = db.get(Trainee, trainee_id)
    t.share_token = None
    db.commit()
    return RedirectResponse(f"/trainees/{trainee_id}?msg=updated", status_code=303)


@router.get("/{trainee_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_trainee(
    request: Request, trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    trainee = db.get(Trainee, trainee_id)
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    # Vorhandene Ausnahmen (Overrides) des Trainees, sortiert nach Jahr -
    # dienen NUR der Anzeige/Loeschung; keine Vorauswahl irgendeiner Klasse.
    overrides = db.exec(
        select(TraineeClassMembership)
        .where(TraineeClassMembership.trainee_id == trainee_id)
        .order_by(TraineeClassMembership.schoolyear_id)
    ).all()
    classes_by_id = {c.id: c for c in classes}

    # Beruf-Vorbelegung + Sonderfall-Erkennung aus der aktuellen Einstiegsklasse
    beruf_selected = ""
    sonderfall_checked = False
    if trainee.klasse_id:
        aktuelle_klasse = next((c for c in classes if c.id == trainee.klasse_id), None)
        if aktuelle_klasse is not None:
            token, lehrjahr = beruf_und_lehrjahr(aktuelle_klasse.name)
            beruf_selected = token
            # DH-Kohorten (lj is None) sind ueber den Beruf ableitbar - kein
            # Sonderfall. Nur ein abweichendes LJ (lj != 1) ist ein Sonderfall.
            sonderfall_checked = lehrjahr is not None and lehrjahr != 1

    return templates.TemplateResponse(request, "trainees/form.html", {
        "trainee": trainee,
        "classes": classes,
        "classes_by_id": classes_by_id,
        "rollen": list(TraineeRolle),
        "years": years,
        "overrides": overrides,
        "beruf_optionen": beruf_optionen(classes),
        "beruf_selected": beruf_selected,
        "beruf_art_map": beruf_art_map(classes),
        "sonderfall_checked": sonderfall_checked,
        "active_nav": "trainees",
    })


@router.post("/{trainee_id:int}", response_class=RedirectResponse)
def update_trainee(
    trainee_id: int, db: DB,
    vorname: Annotated[str, Form()],
    nachname: Annotated[str, Form()],
    rolle: Annotated[TraineeRolle, Form()],
    klasse_id: Annotated[str, Form()] = "",
    beruf: Annotated[str, Form()] = "",
    sonderfall: Annotated[str, Form()] = "",
    membership_year_id: Annotated[str, Form()] = "",
    membership_klasse_id: Annotated[str, Form()] = "",
    steckbrief: Annotated[str, Form()] = "",
    aktiv: Annotated[str, Form()] = "",
    ausbildungsbeginn: Annotated[str, Form()] = "",
    upn: Annotated[str, Form()] = "",
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    ausbildungsbeginn_parsed, err = _parse_ausbildungsbeginn(ausbildungsbeginn)
    if err:
        return RedirectResponse(
            f"/trainees/{trainee_id}/bearbeiten?msg=error&detail={urllib.parse.quote(err)}",
            status_code=303,
        )

    klasse_id_int, err = _resolve_einstiegsklasse_id(db, sonderfall, klasse_id, beruf)
    if err:
        return RedirectResponse(
            f"/trainees/{trainee_id}/bearbeiten?msg=error&detail={urllib.parse.quote(err)}",
            status_code=303,
        )

    t = db.get(Trainee, trainee_id)
    t.vorname = vorname
    t.nachname = nachname
    t.rolle = rolle
    t.steckbrief = steckbrief
    t.aktiv = bool(aktiv)
    t.upn = upn.strip() or None
    t.ausbildungsbeginn = ausbildungsbeginn_parsed
    # Einstiegsklasse (Anker) ueber Sonderfall/Beruf ermittelt
    t.klasse_id = klasse_id_int
    # Optionaler Membership-Override fuer ein bestimmtes Schuljahr
    mem_klasse_int = int(membership_klasse_id) if membership_klasse_id else None
    if membership_year_id and mem_klasse_int:
        upsert_membership(db, trainee_id, membership_year_id, mem_klasse_int)
    db.add(t)
    db.commit()
    sync_trainee(db, trainee_id)
    redirect_url = f"/trainees/{trainee_id}?msg=updated"
    warnungen = []
    beginn_warnung = _ausbildungsbeginn_warnung(ausbildungsbeginn_parsed)
    if beginn_warnung:
        warnungen.append(beginn_warnung)
    klasse_fuer_warnung = db.get(TraineeClass, klasse_id_int) if klasse_id_int else None
    art_warnung = _rolle_art_warnung(rolle, klasse_fuer_warnung.art if klasse_fuer_warnung else "AUSBILDUNG")
    if art_warnung:
        warnungen.append(art_warnung)
    if warnungen:
        redirect_url += f"&warnung={urllib.parse.quote(' '.join(warnungen))}"
    return RedirectResponse(redirect_url, status_code=303)


@router.post("/{trainee_id:int}/ausnahme-loeschen", response_class=RedirectResponse)
def ausnahme_loeschen(
    trainee_id: int, db: DB,
    schoolyear_id: Annotated[str, Form()],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Loescht eine einzelne Klassen-Ausnahme (Override) eines Trainees fuer ein Schuljahr.

    Der Anker (trainee.klasse_id) bleibt unberuehrt - klasse_fuer() faellt danach
    wieder auf die reine Berechnung zurueck.
    """
    membership = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee_id,
            TraineeClassMembership.schoolyear_id == schoolyear_id,
        )
    ).first()
    if membership is not None:
        db.delete(membership)
        db.commit()
        sync_trainee(db, trainee_id)
    return RedirectResponse(f"/trainees/{trainee_id}/bearbeiten?msg=updated", status_code=303)


@router.post("/{trainee_id:int}/reaktivieren", response_class=RedirectResponse)
def reaktivieren_trainee(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Archivierter Azubi wird reaktiviert (aktiv=True)."""
    t = db.get(Trainee, trainee_id)
    t.aktiv = True
    db.add(t)
    db.commit()
    return RedirectResponse("/trainees/?status=archiviert&msg=updated", status_code=303)


@router.post("/{trainee_id:int}/loeschen", response_class=RedirectResponse)
def loeschen_trainee(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Endgueltiges Loeschen eines Trainees inkl. aller abhaengigen Zeilen.

    Explizites Vorab-Loeschen von Assignment, TraineeWish, TraineeClassMembership
    stellt korrekte Funktion sowohl unter SQLite (FK-Enforcement evtl. inaktiv)
    als auch unter PostgreSQL (FK-Enforcement aktiv) sicher.
    """
    # Abhaengige Zeilen explizit loeschen (robust fuer SQLite + Postgres)
    assignments = db.exec(
        select(Assignment).where(Assignment.trainee_id == trainee_id)
    ).all()
    for a in assignments:
        db.delete(a)

    wishes = db.exec(
        select(TraineeWish).where(TraineeWish.trainee_id == trainee_id)
    ).all()
    for w in wishes:
        db.delete(w)

    memberships = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee_id
        )
    ).all()
    for m in memberships:
        db.delete(m)

    for bt in db.exec(select(BetreuerTrainee).where(BetreuerTrainee.trainee_id == trainee_id)).all():
        db.delete(bt)

    t = db.get(Trainee, trainee_id)
    db.delete(t)
    db.commit()
    return RedirectResponse("/trainees/?status=archiviert&msg=deleted", status_code=303)


@router.delete("/{trainee_id:int}")
def delete_trainee(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """HTMX-kompatibler DELETE-Endpoint fuer die Aktiv-Liste (direkte Aktion ohne Archiv)."""
    # Abhaengige Zeilen explizit loeschen
    for a in db.exec(select(Assignment).where(Assignment.trainee_id == trainee_id)).all():
        db.delete(a)
    for w in db.exec(select(TraineeWish).where(TraineeWish.trainee_id == trainee_id)).all():
        db.delete(w)
    for m in db.exec(select(TraineeClassMembership).where(TraineeClassMembership.trainee_id == trainee_id)).all():
        db.delete(m)
    for bt in db.exec(select(BetreuerTrainee).where(BetreuerTrainee.trainee_id == trainee_id)).all():
        db.delete(bt)
    t = db.get(Trainee, trainee_id)
    db.delete(t)
    db.commit()
    return HTMLResponse("")
