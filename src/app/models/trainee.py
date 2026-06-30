from enum import Enum

from sqlmodel import Field, SQLModel


class TraineeRolle(str, Enum):
    AZUBI = "AZUBI"
    DH_STUDENT = "DH_STUDENT"
    PRAKTIKANT = "PRAKTIKANT"
    UMSCHUELER = "UMSCHUELER"


class Trainee(SQLModel, table=True):
    __tablename__ = "trainee"

    id: int | None = Field(default=None, primary_key=True)
    vorname: str = Field(max_length=64)
    nachname: str = Field(max_length=64)
    klasse_id: int | None = Field(
        default=None,
        foreign_key="trainee_class.id",
        ondelete="SET NULL",
        index=True,
    )
    rolle: TraineeRolle
    aktiv: bool = Field(default=True)
    notizen: str = Field(default="")
    # Frei editierbarer Steckbrief-Text (Visitenkarte im Profil)
    steckbrief: str = Field(default="")
    # Self-Service: Capability-Token fuer /mein-plan/{token}; None = kein Zugang
    share_token: str | None = Field(default=None, max_length=36, unique=True, index=True)
    # Freitext-Wuensche des Azubis (inkl. Zeitwuensche) -- beratend fuer die Planerin
    wunsch_notiz: str = Field(default="")
