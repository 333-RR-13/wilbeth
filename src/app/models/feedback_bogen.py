from datetime import date

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class FeedbackBogen(SQLModel, table=True):
    """Feedbackbogen zu einem Abteilungs-Einsatz eines Trainees.

    Zwei Typen (Feld "typ"):
    - "AUSBILDER" (bogen_version "DE-2019"): Fachausbilder beurteilt den Azubi.
    - "AZUBI" (bogen_version "DE-2024"): Azubi beurteilt den Einsatz/die
      Abteilung (Selbsteinschaetzung bei den Lernzielen).

    Betrifft einen KW-Block (kw_von/jahr_von .. kw_bis/jahr_bis) eines
    Trainees in einer Abteilung, analog EinsatzVorschlag.

    WICHTIG bei den JSON-Spalten (lernziele, antworten, freitexte): SQLAlchemy
    erkennt In-Place-Mutationen (z. B. bogen.antworten["x"] = 1 oder
    bogen.lernziele.append(...)) NICHT automatisch. Beim Aendern immer eine
    NEUE Liste/ein neues Dict zuweisen, z. B.:
        bogen.antworten = {**bogen.antworten, "x": 1}
        bogen.lernziele = [*bogen.lernziele, {"text": "...", "bewertung": None}]
    """

    __tablename__ = "feedback_bogen"

    id: int | None = Field(default=None, primary_key=True)
    typ: str  # "AUSBILDER" | "AZUBI"
    bogen_version: str = Field(default="")

    trainee_id: int = Field(foreign_key="trainee.id", index=True)
    department_id: int = Field(foreign_key="department.id", index=True)
    schoolyear_id: str = Field(foreign_key="schoolyear.id", index=True)

    kw_von: int
    jahr_von: int
    kw_bis: int
    jahr_bis: int

    einsatzart: str = Field(default="")  # "Ersteinsatz" | "Folgeeinsatz" | "Projekteinsatz"
    fachausbilder_name: str = Field(default="")

    # [{"text": str, "bewertung": int | None}, ...]
    lernziele: list = Field(default_factory=list, sa_column=Column(JSON))
    # {frage_key: 1..5, ...}
    antworten: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # {feld_key: str, ...}
    freitexte: dict = Field(default_factory=dict, sa_column=Column(JSON))

    # Fehlzeiten in WOCHEN (nur Typ AUSBILDER; urlaub/schule werden aus dem
    # Plan vorbelegt, koennen aber ueberschrieben werden)
    fehl_krank: int | None = Field(default=None)
    fehl_urlaub: int | None = Field(default=None)
    fehl_schule: int | None = Field(default=None)
    fehl_sonstige: int | None = Field(default=None)

    weiterer_einsatz: str = Field(default="")  # "ja" | "nein" | ""
    zugriffe_geloescht: bool = Field(default=False)

    status: str = Field(default="entwurf")  # entwurf|abgeschlossen|besprochen|bestaetigt
    besprochen_am: date | None = Field(default=None)
    bestaetigt_am: date | None = Field(default=None)

    erstellt_von_upn: str = Field(default="")
    erstellt_am: date | None = Field(default=None)
    aktualisiert_am: date | None = Field(default=None)
