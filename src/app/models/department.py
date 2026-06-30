from typing import Optional, List

from sqlmodel import Field, Relationship, SQLModel


class DepartmentKategorie(SQLModel, table=True):
    __tablename__ = "department_kategorie"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=64, unique=True, index=True)

    # back-reference
    departments: List["Department"] = Relationship(back_populates="kategorie")


class Department(SQLModel, table=True):
    __tablename__ = "department"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(max_length=16, unique=True, index=True)
    name: str = Field(max_length=128)
    kategorie_id: int | None = Field(default=None, foreign_key="department_kategorie.id", index=True)
    ansprechpartner: str = Field(default="")
    info_text: str = Field(default="")
    erlaubt_mehrfachbelegung: bool = Field(default=False)
    farbe: str = Field(default="#9CA3AF")

    # relationship – lädt die DepartmentKategorie automatisch (für Templates: d.kategorie.name)
    kategorie: Optional[DepartmentKategorie] = Relationship(back_populates="departments")
