from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

# ── Prioritäts-Labels (1 = Muss, 2 = Sollte, 3 = Kann) ───────────────────────
# Das DB-Feld bleibt int; diese Tabelle und der Helfer übersetzen für die Anzeige.
PRIORITAET_LABELS: dict[int, str] = {1: "Muss", 2: "Sollte", 3: "Kann"}


def prioritaet_label(p: int) -> str:
    """Gibt den semantischen Label für eine Priorität zurück.

    >>> prioritaet_label(1)
    'Muss'
    >>> prioritaet_label(2)
    'Sollte'
    >>> prioritaet_label(3)
    'Kann'
    """
    return PRIORITAET_LABELS.get(p, str(p))


class TraineeWish(SQLModel, table=True):
    """Abteilungs-Wunsch eines Trainees mit Prioritaet.

    Maschinenlesbarer Teil der Wunschliste (wird vom Auto-Planer in Sprint 7
    beruecksichtigt). Zeitwuensche/Freitext liegen separat in Trainee.wunsch_notiz.
    """

    __tablename__ = "trainee_wish"
    __table_args__ = (
        UniqueConstraint("trainee_id", "department_id", name="uq_wish_trainee_dept"),
    )

    id: int | None = Field(default=None, primary_key=True)
    trainee_id: int = Field(foreign_key="trainee.id", ondelete="CASCADE", index=True)
    department_id: int = Field(foreign_key="department.id", ondelete="CASCADE")
    prioritaet: int = Field(default=2)  # 1 = Muss, 2 = Sollte, 3 = Kann
