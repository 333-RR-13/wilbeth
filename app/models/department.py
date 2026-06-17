from enum import Enum

from sqlmodel import Field, SQLModel


class DepartmentKategorie(str, Enum):
    ITO = "ITO"
    NON_ITO = "NON_ITO"
    EXTERN = "EXTERN"


class Department(SQLModel, table=True):
    __tablename__ = "department"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(max_length=16, unique=True, index=True)
    name: str = Field(max_length=128)
    kategorie: DepartmentKategorie
    ansprechpartner: str = Field(default="")
    erlaubt_mehrfachbelegung: bool = Field(default=False)
    farbe: str = Field(default="#9CA3AF")
