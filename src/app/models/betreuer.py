from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

# Funktion einer betreuenden Person -- kleine Enum-artige Konstante (kein
# echtes Enum, analog BEREICH_LABELS/ART_LABELS in app/models/trainee_class.py)
# mit den UI-Labels (echte Umlaute, landet direkt in Templates/Flash-Texten).
FUNKTION_LABELS: dict[str, str] = {
    "HR": "Ausbildung (HR)",
    "TECHNISCH": "Fachlicher Ausbilder",
    "EINSATZPLANUNG": "Einsatzplanung",
    "SONSTIGES": "Sonstiges",
}

# Reihenfolge, in der Funktionen in Listen/Sortierungen erscheinen sollen
# (siehe app/services/betreuung_utils.betreuer_fuer_trainee).
FUNKTION_REIHENFOLGE: list[str] = ["HR", "TECHNISCH", "EINSATZPLANUNG", "SONSTIGES"]

# Modus einer Ausnahme in BetreuerTrainee.
MODUS_LABELS: dict[str, str] = {
    "ZUSAETZLICH": "Zusätzlich zugeordnet",
    "AUSGENOMMEN": "Ausgenommen",
}


class Betreuer(SQLModel, table=True):
    """Person, die einen Azubi/Studi ueber die GESAMTE Ausbildung begleitet --
    im Unterschied zu den abteilungsbezogenen Ausbildern (Department.
    verantwortliche, s. app/services/verantwortliche_utils.py), deren
    Zustaendigkeit auf den jeweiligen Einsatz beschraenkt ist.

    Beispiele (siehe Aufgabenstellung): eine HR-Ausbilderin fuer alle
    Studiengaenge/Buerokaufleute/ITler, zwei technische Ausbilder nur fuer
    FISI, eine Einsatzplanerin fuer alle IT-Azubis/-Studis.

    berufe: Liste von Beruf-Tokens (wie membership_utils.beruf_optionen sie
    liefert, z. B. ["FISI", "FIAE"]). LEERE Liste bedeutet ausdruecklich
    "zustaendig fuer ALLE Berufe" -- exakt dasselbe Muster wie
    Department.erlaubte_berufe (siehe app/models/department.py). WICHTIG:
    SQLModel erkennt In-Place-Mutationen an JSON-Spalten nicht -- beim
    Aendern immer eine neue Liste zuweisen (siehe Kommentar in
    app/models/feedback_bogen.py).

    Die konkrete Zustaendigkeits-Regel (inkl. der Ausnahmen ueber
    BetreuerTrainee) steht in app/services/betreuung_utils.py.
    """

    __tablename__ = "betreuer"

    id: int | None = Field(default=None, primary_key=True)
    upn: str = Field(unique=True, index=True)
    name: str = Field(default="")
    funktion: str = Field(default="SONSTIGES")
    email: str = Field(default="")
    telefon: str = Field(default="")
    # Interne Notiz -- wird dem Azubi NIE angezeigt (siehe
    # app/routers/share.py: nur Name/Funktion/E-Mail/Telefon sind dort sichtbar).
    notiz: str = Field(default="")
    aktiv: bool = Field(default=True)
    berufe: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class BetreuerTrainee(SQLModel, table=True):
    """Ausnahme von der Beruf-Regel eines Betreuers fuer einen einzelnen Trainee.

    modus:
      "ZUSAETZLICH" -- dieser Trainee wird betreut, OBWOHL sein Beruf nicht
                        in Betreuer.berufe steht (bzw. der Betreuer inaktiv-
                        unabhaengig zusaetzlich zustaendig gemacht wird).
      "AUSGENOMMEN" -- dieser Trainee wird NICHT betreut, OBWOHL sein Beruf
                        zu Betreuer.berufe passt.

    Pro (betreuer_id, trainee_id)-Paar darf es nur GENAU EINE Ausnahme geben
    (ein Trainee kann fuer denselben Betreuer nicht gleichzeitig zusaetzlich
    UND ausgenommen sein) -- siehe UniqueConstraint unten.
    """

    __tablename__ = "betreuer_trainee"
    __table_args__ = (
        UniqueConstraint("betreuer_id", "trainee_id", name="uq_betreuer_trainee"),
    )

    id: int | None = Field(default=None, primary_key=True)
    betreuer_id: int = Field(foreign_key="betreuer.id", ondelete="CASCADE", index=True)
    trainee_id: int = Field(foreign_key="trainee.id", ondelete="CASCADE", index=True)
    modus: str = Field(default="ZUSAETZLICH")
