from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.database import init_db
from app.routers import (
    about,
    assignments,
    departments,
    holidays,
    overview,
    school_plans,
    schoolyears,
    share,
    trainee_classes,
    trainees,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Wilbeth", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(overview.router)
app.include_router(schoolyears.router)
app.include_router(holidays.router)
app.include_router(departments.router)
app.include_router(trainee_classes.router)
app.include_router(trainees.router)
app.include_router(school_plans.router)
app.include_router(assignments.router)
app.include_router(share.router)
app.include_router(about.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
