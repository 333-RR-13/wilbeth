from sqlmodel import Field, SQLModel


class SchoolHoliday(SQLModel, table=True):
    __tablename__ = "school_holiday"

    id: int | None = Field(default=None, primary_key=True)
    schoolyear_id: str = Field(foreign_key="schoolyear.id", index=True)
    name: str = Field(max_length=64)
    start_kw: int
    start_year: int
    end_kw: int
    end_year: int
