from typing import Optional, List

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

# ABGELOEST durch Department.erlaubte_berufe (s. u., seit Migration
# 0016berufe / TEIL B) -- nicht mehr in UI/Konfliktpruefung genutzt, nur
# noch als Doku fuer die alten Werte der (weiterhin in der DB stehenden)
# Spalte zielgruppe stehen gelassen: "IT" (nur IT-Azubis/-Studis),
# "KAUFMAENNISCH" (nur kaufmaennische Azubis/-Studis), "BEIDE" (Default --
# nahm beide Bereiche).
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
    # Prominenter externer Link auf der Abteilungs-Infoseite (z. B. Confluence).
    # Nur http/https wird akzeptiert (siehe app/utils/text.is_safe_http_url) --
    # geprueft beim Speichern in app/routers/departments.py bzw.
    # app/routers/ausbilder.py (Migration 0015infolink).
    info_link: str = Field(default="")
    erlaubt_mehrfachbelegung: bool = Field(default=False)
    farbe: str = Field(default="#9CA3AF")
    verantwortliche: str = Field(default="")
    # ZIELGRUPPE IST FACHLICH ABGELOEST durch erlaubte_berufe (s. u., seit
    # Migration 0016berufe / TEIL B). Die Spalte bleibt in der DB stehen
    # (Datensicherung/Ruckwaertskompatibilitaet), wird aber seither weder in
    # der UI noch in der Konfliktpruefung mehr ausgewertet -- NICHT weiter
    # pflegen.
    zielgruppe: str = Field(default="BEIDE", max_length=32)
    # Liste erlaubter Beruf-Tokens (wie von membership_utils.beruf_optionen
    # geliefert, z. B. ["FISI", "FIAE"]), die in dieser Abteilung eingesetzt
    # werden koennen. LEERE Liste (Default) bedeutet ausdruecklich "alle
    # Berufe erlaubt" -- das ist der bisherige Zustand "BEIDE". Genutzt fuer
    # die Bereich-Konfliktpruefung (siehe services/conflict_checker.py,
    # ConflictKind.BEREICH_KONFLIKT). WICHTIG: SQLModel erkennt In-Place-
    # Mutationen an JSON-Spalten nicht -- beim Aendern immer eine neue Liste
    # zuweisen (siehe Kommentar in app/models/feedback_bogen.py).
    erlaubte_berufe: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # relationship – lädt die DepartmentKategorie automatisch (für Templates: d.kategorie.name)
    kategorie: Optional[DepartmentKategorie] = Relationship(back_populates="departments")
