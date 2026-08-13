"""Hilfsfunktionen fuer die Betreuer-Zustaendigkeit (Personen, die einen
Trainee ueber die gesamte Ausbildung begleiten, s. app/models/betreuer.py).

Regel: ein aktiver Betreuer ist fuer einen Trainee zustaendig, wenn
  (a) Betreuer.berufe leer ist (= alle Berufe) ODER der fuer das Schuljahr
      BERECHNETE Beruf-Token des Trainees (membership_utils.klasse_fuer +
      beruf_und_lehrjahr) in Betreuer.berufe steht,
UND es keine "AUSGENOMMEN"-Ausnahme (BetreuerTrainee) fuer dieses Paar gibt.
Eine "ZUSAETZLICH"-Ausnahme macht den Betreuer IMMER zustaendig, unabhaengig
von (a). Trainees ohne berechnete Klasse (klasse_fuer -> None, z. B.
Absolventen oder Zieljahr vor Ausbildungsbeginn) werden nur ueber eine
"ZUSAETZLICH"-Ausnahme erfasst.

betreuer_fuer_trainee() und trainees_fuer_betreuer() sind zueinander
konsistent: was die eine liefert, liefert die andere in umgekehrter
Richtung ebenfalls (dieselbe _ist_zustaendig-Regel).
"""

from sqlmodel import Session, select

from app.models.betreuer import FUNKTION_REIHENFOLGE, Betreuer, BetreuerTrainee
from app.models.department import Department
from app.models.trainee import Trainee
from app.models.trainee_class import TraineeClass
from app.services.dept_history import visited_department_ids
from app.services.membership_utils import aktuelles_schuljahr_id, beruf_und_lehrjahr, klasse_fuer
from app.services.verantwortliche_utils import parse_verantwortliche


def _beruf_token_fuer_trainee(
    db: Session,
    trainee: Trainee,
    schoolyear_id: str | None,
    classes_by_id: dict[int, TraineeClass] | None = None,
) -> str | None:
    """Berechneter Beruf-Token des Trainees fuers Schuljahr, oder None (kein
    Schuljahr aufloesbar / keine berechnete Klasse, z. B. Absolvent)."""
    if not schoolyear_id:
        return None
    klasse_id = klasse_fuer(db, trainee, schoolyear_id)
    if klasse_id is None:
        return None
    klasse = classes_by_id.get(klasse_id) if classes_by_id is not None else db.get(TraineeClass, klasse_id)
    if klasse is None:
        return None
    beruf_token, _lj = beruf_und_lehrjahr(klasse.name)
    return beruf_token


def _ist_zustaendig(betreuer: Betreuer, beruf_token: str | None, modus_ausnahme: str | None) -> bool:
    if modus_ausnahme == "AUSGENOMMEN":
        return False
    if modus_ausnahme == "ZUSAETZLICH":
        return True
    if beruf_token is None:
        return False
    if not betreuer.berufe:
        return True
    return beruf_token in betreuer.berufe


def _betreuer_sort_key(b: Betreuer) -> tuple[int, str]:
    idx = FUNKTION_REIHENFOLGE.index(b.funktion) if b.funktion in FUNKTION_REIHENFOLGE else len(FUNKTION_REIHENFOLGE)
    return (idx, (b.name or b.upn).lower())


def betreuer_fuer_trainee(db: Session, trainee: Trainee, schoolyear_id: str | None = None) -> list[Betreuer]:
    """Alle aktiven Betreuer, die fuer diesen Trainee zustaendig sind.

    schoolyear_id: None -> das laufende Schuljahr (aktuelles_schuljahr_id).
    Sortiert nach Funktion (HR, TECHNISCH, EINSATZPLANUNG, SONSTIGES), dann
    Name/UPN.
    """
    if schoolyear_id is None:
        schoolyear_id = aktuelles_schuljahr_id(db)

    beruf_token = _beruf_token_fuer_trainee(db, trainee, schoolyear_id)

    exceptions = {
        bt.betreuer_id: bt.modus
        for bt in db.exec(select(BetreuerTrainee).where(BetreuerTrainee.trainee_id == trainee.id)).all()
    }

    alle_betreuer = db.exec(select(Betreuer).where(Betreuer.aktiv == True)).all()  # noqa: E712
    result = [
        b for b in alle_betreuer
        if _ist_zustaendig(b, beruf_token, exceptions.get(b.id))
    ]
    return sorted(result, key=_betreuer_sort_key)


def trainees_fuer_betreuer(db: Session, betreuer: Betreuer, schoolyear_id: str | None = None) -> list[Trainee]:
    """Alle aktiven Trainees, fuer die dieser Betreuer zustaendig ist
    (Umkehrung von betreuer_fuer_trainee).

    Effizienz: aktive Trainees, Ausnahmen und Klassen werden je EINMAL
    geladen und in Python ausgewertet (kein DB-Zugriff pro Trainee -- analog
    app.services.abwesenheit_utils.abwesenheit_map). Sortiert nach
    Nachname/Vorname.

    Ein inaktiver Betreuer liefert IMMER eine leere Liste -- symmetrisch zu
    betreuer_fuer_trainee(), das inaktive Betreuer generell ausschliesst
    (sonst waeren beide Richtungen inkonsistent).
    """
    if not betreuer.aktiv:
        return []

    if schoolyear_id is None:
        schoolyear_id = aktuelles_schuljahr_id(db)

    all_active = db.exec(select(Trainee).where(Trainee.aktiv == True)).all()  # noqa: E712
    exceptions = {
        bt.trainee_id: bt.modus
        for bt in db.exec(select(BetreuerTrainee).where(BetreuerTrainee.betreuer_id == betreuer.id)).all()
    }
    classes_by_id = {c.id: c for c in db.exec(select(TraineeClass)).all()}

    result = []
    for t in all_active:
        beruf_token = _beruf_token_fuer_trainee(db, t, schoolyear_id, classes_by_id)
        if _ist_zustaendig(betreuer, beruf_token, exceptions.get(t.id)):
            result.append(t)

    return sorted(result, key=lambda t: (t.nachname, t.vorname))


def abteilungs_ansprechpartner(db: Session, trainee_id: int) -> list[dict]:
    """Ansprechpartner in den Abteilungen, in denen ein Trainee eingesetzt ist
    oder war (app.services.dept_history.visited_department_ids, ALLE
    Einsaetze, nicht nur vergangene -- ein laufender/geplanter Einsatz soll
    seine Ansprechpartner ebenfalls zeigen).

    Andere Zustaendigkeit als betreuer_fuer_trainee()/Betreuer oben: hier
    geht es um die ABTEILUNGS-Ausbilder aus Department.verantwortliche
    (Freitext-UPN-Liste, s. app/services/verantwortliche_utils.py), deren
    Zustaendigkeit auf den jeweiligen Einsatz beschraenkt ist.

    Je Eintrag in Department.verantwortliche wird versucht, per UPN (case-
    insensitiver Vergleich) einen passenden Betreuer-Datensatz zu finden --
    existiert einer, werden Klarname+Kontakt geliefert, sonst die rohe UPN
    (unveraendert). Zusaetzlich liefert jede Zeile Department.ansprechpartner
    (der freie fachliche Ansprechpartner-Text der Abteilung), falls gepflegt.

    Rueckgabe, sortiert nach Department.code (leer, wenn der Trainee noch
    keinen Abteilungs-Einsatz hatte):
      [{"department": Department,
        "personen": [{"anzeige": str, "betreuer": Betreuer | None}, ...],
        "ansprechpartner": str}, ...]
    """
    ids = visited_department_ids(db, trainee_id)
    if not ids:
        return []

    depts = db.exec(
        select(Department).where(Department.id.in_(ids)).order_by(Department.code)  # type: ignore[union-attr]
    ).all()

    betreuer_by_upn = {
        b.upn.strip().lower(): b for b in db.exec(select(Betreuer)).all() if b.upn
    }

    result = []
    for dept in depts:
        personen = []
        for upn in parse_verantwortliche(dept.verantwortliche):
            b = betreuer_by_upn.get(upn.strip().lower())
            personen.append({
                "anzeige": (b.name if b.name else b.upn) if b is not None else upn,
                "betreuer": b,
            })
        result.append({
            "department": dept,
            "personen": personen,
            "ansprechpartner": dept.ansprechpartner,
        })
    return result
