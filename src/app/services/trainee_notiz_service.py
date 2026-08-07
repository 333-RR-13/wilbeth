"""Schreib-Logik fuer TraineeNotiz (Notiz-Verlauf ueber einen Trainee).

Wird von zwei Routen genutzt: app.routers.trainees (Profil-Direkteingabe,
kein Einsatz-Kontext) und app.routers.ausbilder (Notiz aus einem Einsatz-
Block heraus, MIT Einsatz-Kontext). Die Berechtigungsregel unterscheidet
sich bewusst je nach Kontext (siehe darf_notiz_anlegen) und weicht damit vom
Bestandsverhalten der uebrigen /meine-abteilung/-Routen ab, die JEDE Rolle
(auch orga/admin) auf die eigene verantwortliche UPN beschraenken -- hier
duerfen orga/admin uneingeschraenkt Notizen zu jedem Trainee anlegen.
"""
from datetime import date

from sqlmodel import Session

from app.models.trainee_notiz import TraineeNotiz
from app.services.auth_service import CurrentUser, allowed_dept_ids
from app.services.dept_history import visited_department_ids


def darf_notiz_anlegen(
    db: Session,
    user: CurrentUser,
    trainee_id: int,
    department_id: int | None = None,
) -> bool:
    """Prueft, ob user fuer trainee_id eine TraineeNotiz anlegen darf.

    - orga/admin: immer erlaubt.
    - ausbilder MIT department_id (Block-Kontext): erlaubt genau dann, wenn
      department_id in allowed_dept_ids(db, user).
    - ausbilder OHNE department_id (Profil-Direkteingabe): erlaubt genau
      dann, wenn allowed_dept_ids(db, user) & visited_department_ids(db,
      trainee_id) nicht leer ist -- dieselbe Regel wie die bestehende Lese-
      Ausnahme in trainees.py::trainee_detail().
    - sonst (z. B. azubi): nie erlaubt.
    """
    if user.rolle in ("orga", "admin"):
        return True
    if user.rolle != "ausbilder":
        return False
    if department_id is not None:
        return department_id in allowed_dept_ids(db, user)
    return bool(allowed_dept_ids(db, user) & visited_department_ids(db, trainee_id))


def erstelle_notiz(
    db: Session,
    user: CurrentUser,
    trainee_id: int,
    text: str,
    department_id: int | None = None,
    kw_von: int | None = None,
    jahr_von: int | None = None,
    kw_bis: int | None = None,
    jahr_bis: int | None = None,
) -> TraineeNotiz | None:
    """Legt eine TraineeNotiz an. Gibt bei leerem (nach .strip()) Text None
    zurueck, ohne zu schreiben -- die aufrufende Route entscheidet, wie sie
    das dem Nutzer meldet (kein 500er)."""
    text_stripped = (text or "").strip()
    if not text_stripped:
        return None

    notiz = TraineeNotiz(
        trainee_id=trainee_id,
        text=text_stripped,
        verfasser_upn=user.upn,
        verfasser_name=user.name,
        erstellt_am=date.today(),
        department_id=department_id,
        kw_von=kw_von,
        jahr_von=jahr_von,
        kw_bis=kw_bis,
        jahr_bis=jahr_bis,
    )
    db.add(notiz)
    db.commit()
    db.refresh(notiz)
    return notiz
