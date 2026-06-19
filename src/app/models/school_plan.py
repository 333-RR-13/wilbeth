from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class SchoolWeekTyp(str, Enum):
    BERUFSSCHULE = "BERUFSSCHULE"
    UNI = "UNI"


class SchoolPlan(SQLModel, table=True):
    __tablename__ = "school_plan"
    __table_args__ = (
        UniqueConstraint("klasse_id", "schoolyear_id", name="uq_plan_klasse_year"),
    )

    id: int | None = Field(default=None, primary_key=True)
    klasse_id: int = Field(foreign_key="trainee_class.id", index=True)
    schoolyear_id: str = Field(foreign_key="schoolyear.id", index=True)


class SchoolPlanWeek(SQLModel, table=True):
    __tablename__ = "school_plan_week"
    __table_args__ = (
        UniqueConstraint("plan_id", "kw", "jahr", name="uq_planweek_plan_kw_jahr"),
    )

    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="school_plan.id", index=True)
    kw: int = Field(index=True)
    jahr: int = Field(index=True)
    typ: SchoolWeekTyp
