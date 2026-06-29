from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter(tags=["about"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")


@router.get("/ueber-wilbeth", response_class=HTMLResponse)
def about_wilbeth(request: Request):
    return templates.TemplateResponse(request, "about/wilbeth.html", {
        "active_nav": "about",
    })


@router.get("/roadmap", response_class=HTMLResponse)
def roadmap(request: Request):
    # Temporaere Seite fuer die Aufbauphase – vor dem produktiven Deploy entfernen.
    return templates.TemplateResponse(request, "roadmap.html", {
        "active_nav": "roadmap",
    })
