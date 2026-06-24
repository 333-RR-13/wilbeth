from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class TraineeClassMembership(SQLModel, table=True):
    """Ordnet einen Trainee einer Klasse fuer ein bestimmtes Lehrjahr zu.

    Pro (trainee_id, schoolyear_id) darf es nur eine Membership geben.
    trainee.klasse_id bleibt als aktuelle/Default-Klasse erhalten (Fallback).
    """

    __tablename__ = "trainee_class_membership"
    __table_args__ = (
        UniqueConstraint("trainee_id", "schoolyear_id", name="uq_membership_trainee_year"),
    )

    id: int | None = Field(default=None, primary_key=True)
    trainee_id: int = Field(
        foreign_key="trainee.id",
        ondelete="CASCADE",
        index=True,
    )
    schoolyear_id: str = Field(foreign_key="schoolyear.id", index=True)
    klasse_id: int = Field(foreign_key="trainee_class.id", index=True)
