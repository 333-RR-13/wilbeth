from sqlmodel import Field, SQLModel


class Schoolyear(SQLModel, table=True):
    __tablename__ = "schoolyear"

    id: str = Field(primary_key=True, max_length=16)
    start_kw: int
    start_year: int
    end_kw: int
    end_year: int
    archiviert: bool = Field(default=False)
