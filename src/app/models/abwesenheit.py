from datetime import date
from enum import Enum

from sqlmodel import Field, SQLModel


class AbwesenheitTyp(str, Enum):
    URLAUB = "URLAUB"
    SONSTIGES = "SONSTIGES"


class AbwesenheitQuelle(str, Enum):
    SELBST = "SELBST"
    PLANER = "PLANER"
    SAP = "SAP"


class Abwesenheit(SQLModel, table=True):
    """Tagegenauer Abwesenheitszeitraum eines Trainees (Ueberlagerung, kein Assignment).

    Ersetzt den bisherigen Assignment-Typ URLAUB als eigenstaendige Tabelle:
    ein Zeitraum (von_datum..bis_datum, beide inklusive, ganze Tage, keine
    Halbtage) blockiert die Einsatzmatrix NICHT mehr, sondern wird dort nur
    als Markierung (siehe app.services.abwesenheit_utils.abwesenheit_map)
    ueberlagert. Dadurch kann ein Trainee in derselben Kalenderwoche
    weiterhin einer Abteilung zugeordnet sein.

    quelle dokumentiert die Herkunft: SELBST (Azubi via /mein-plan),
    PLANER (im Admin/Planer angelegt) oder SAP (reserviert fuer eine
    kuenftige SAP-SuccessFactors-Synchronisation).
    """

    __tablename__ = "abwesenheit"

    id: int | None = Field(default=None, primary_key=True)
    trainee_id: int = Field(foreign_key="trainee.id", ondelete="CASCADE", index=True)
    von_datum: date
    bis_datum: date
    typ: AbwesenheitTyp
    kommentar: str = Field(default="")
    quelle: AbwesenheitQuelle
    erstellt_von_upn: str = Field(default="")
    erstellt_am: date | None = Field(default=None)
