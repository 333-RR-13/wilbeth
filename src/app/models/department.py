from typing import Optional, List

from sqlmodel import Field, Relationship, SQLModel

# Zielgruppe einer Abteilung: "IT" (nur IT-Azubis/-Studis), "KAUFMAENNISCH"
# (nur kaufmaennische Azubis/-Studis) oder "BEIDE" (Default -- nimmt beide
# Bereiche). Label fuer die Anzeige im Formular/UI.
ZIELGRUPPE_LABELS: dict[str, str] = {
    "IT": "Nur IT",
    "KAUFMAENNISCH": "Nur kaufmännisch",
    "BEIDE": "Beide",
}


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
    verantwortliche: str = Field(default="")
    # Zielgruppe ("IT" | "KAUFMAENNISCH" | "BEIDE"), Default "BEIDE" -- damit
    # keine Bestandsplanung durch die Einfuehrung ploetzlich als Konflikt
    # markiert wird. Genutzt fuer die Bereich/Zielgruppe-Konfliktpruefung
    # (siehe services/conflict_checker.py, ConflictKind.BEREICH_KONFLIKT).
    zielgruppe: str = Field(default="BEIDE", max_length=32)

    # relationship – lädt die DepartmentKategorie automatisch (für Templates: d.kategorie.name)
    kategorie: Optional[DepartmentKategorie] = Relationship(back_populates="departments")
