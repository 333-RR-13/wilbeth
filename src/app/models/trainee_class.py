from enum import Enum

from sqlmodel import Field, SQLModel


class UnterrichtsTyp(str, Enum):
    BLOCK_FEST = "BLOCK_FEST"   # feste Blockwochen (FISI, FIAE) – via SchoolPlanWeek
    DH_PHASEN = "DH_PHASEN"     # lange Uni-/Theorieblöcke (DHBW, BWL) – wie BLOCK_FEST
    TAGE_FEST = "TAGE_FEST"     # Wochentag-Schule (Bürokaufleute) – feste Schultage je Woche


class TraineeClass(SQLModel, table=True):
    __tablename__ = "trainee_class"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=64, unique=True, index=True)
    berufsschule: str = Field(max_length=128)
    unterrichts_typ: UnterrichtsTyp
    # Nur fuer TAGE_FEST: feste Schul-Wochentage als ISO-Zahlen (Mo=1..So=7),
    # komma-separiert, z. B. "2,3" = Di, Mi. halbtag_wochentag markiert einen
    # davon als Halbtag (z. B. 3 = Mi). Fuer andere Typen leer/None.
    schul_wochentage: str = Field(default="")
    halbtag_wochentag: int | None = Field(default=None)
