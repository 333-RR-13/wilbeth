from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Index, SQLModel


class AssignmentTyp(str, Enum):
    ABTEILUNG = "ABTEILUNG"
    URLAUB = "URLAUB"
    BERUFSSCHULE = "BERUFSSCHULE"
    UNI = "UNI"
    FREI = "FREI"


class AssignmentSource(str, Enum):
    AUTO = "AUTO"        # vom (geplanten) Auto-Planer erzeugt
    MANUAL = "MANUAL"    # von der Planerin im Admin angelegt
    SELBST = "SELBST"    # vom Azubi selbst eingetragen (z. B. Urlaub via /mein-plan)
    SAP = "SAP"          # reserviert: aus SAP-SuccessFactors synchronisiert


class Assignment(SQLModel, table=True):
    __tablename__ = "assignment"
    __table_args__ = (
        UniqueConstraint("trainee_id", "kw", "jahr", name="uq_assign_trainee_kw_jahr"),
        Index("ix_assign_year_kw_dept", "schoolyear_id", "kw", "abteilung_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    trainee_id: int = Field(foreign_key="trainee.id", ondelete="CASCADE", index=True)
    schoolyear_id: str = Field(foreign_key="schoolyear.id", index=True)
    kw: int
    jahr: int
    typ: AssignmentTyp
    abteilung_id: int | None = Field(
        default=None,
        foreign_key="department.id",
        ondelete="RESTRICT",
    )
    source: AssignmentSource = Field(default=AssignmentSource.MANUAL)
    notiz: str = Field(default="")
