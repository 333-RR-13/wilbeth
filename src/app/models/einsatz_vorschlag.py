from datetime import date

from sqlmodel import Field, SQLModel


class EinsatzVorschlag(SQLModel, table=True):
    """Vorschlag eines Azubis fuer einen kuenftigen Abteilungs-Einsatz.

    Wird ueber /mein-plan eingereicht (Selbstbedienung) und von der
    Planerin/dem Ausbilder angenommen oder abgelehnt. Betrifft einen
    KW-Block (kw_von/jahr_von .. kw_bis/jahr_bis), keine einzelne Zelle.
    """

    __tablename__ = "einsatz_vorschlag"

    id: int | None = Field(default=None, primary_key=True)
    trainee_id: int = Field(foreign_key="trainee.id", index=True)
    department_id: int = Field(foreign_key="department.id", index=True)
    schoolyear_id: str = Field(foreign_key="schoolyear.id", index=True)
    kw_von: int
    jahr_von: int
    kw_bis: int
    jahr_bis: int
    kommentar: str = Field(default="")
    eingereicht_von_upn: str = Field(default="")
    eingereicht_von_name: str = Field(default="")
    status: str = Field(default="offen")  # offen|angenommen|abgelehnt
    antwort_kommentar: str = Field(default="")
    erstellt_am: date | None = Field(default=None)
