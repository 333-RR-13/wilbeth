from datetime import date

from sqlmodel import Field, SQLModel


class TraineeNotiz(SQLModel, table=True):
    """Notiz-Verlauf eines Ausbilders ueber einen Trainee (NICHT einsatzbezogen).

    Anders als Assignment.notiz/Assignment.feedback (die bestehende Notiz/
    Feedback zum EINZELNEN Einsatz-Block) ist dies ein chronologischer
    Verlauf mehrerer Eintraege ueber den Trainee als Person, gesammelt im
    Profil sichtbar. Ersetzt fachlich das alte einzelne Freitextfeld
    Trainee.notizen (bleibt in der DB als Datensicherung bestehen, wird aber
    von der UI nicht mehr befuellt).

    Eine Notiz entsteht entweder direkt im Profil (department_id/kw_* = None)
    oder aus einem Einsatz-Block heraus (department_id + KW-Zeitraum gesetzt,
    dokumentiert den Kontext, in dem sie geschrieben wurde). department_id
    traegt ondelete='SET NULL' -- wird die Abteilung geloescht, bleibt die
    Notiz als Text erhalten, verliert nur den Kontext-Verweis.

    Der Azubi selbst sieht diese Notizen NIE (weder im Self-Service-Bereich
    noch sonstwo) -- siehe app/routers/share.py.
    """

    __tablename__ = "trainee_notiz"

    id: int | None = Field(default=None, primary_key=True)
    trainee_id: int = Field(foreign_key="trainee.id", ondelete="CASCADE", index=True)
    text: str
    verfasser_upn: str = Field(default="")
    verfasser_name: str = Field(default="")
    erstellt_am: date | None = Field(default=None)
    department_id: int | None = Field(default=None, foreign_key="department.id", ondelete="SET NULL")
    kw_von: int | None = Field(default=None)
    jahr_von: int | None = Field(default=None)
    kw_bis: int | None = Field(default=None)
    jahr_bis: int | None = Field(default=None)
