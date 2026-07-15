from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import init_db
from app.routers import (
    about,
    assignments,
    auto_plan,
    auth,
    departments,
    holidays,
    imports,
    jahreswechsel,
    overview,
    school_plans,
    schoolyears,
    share,
    trainee_classes,
    trainees,
)
from app.services.auth_service import SESSION_KEY, CurrentUser, user_from_session

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Wilbeth", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Pfade, die auch ohne Login erreichbar sein muessen: Login-Flow selbst,
# Health-Check (Kubernetes-Probes), Static-Assets und die Azubi-Capability-
# Links unter /mein-plan/{token} (Token *ist* die Authentifizierung dort).
PUBLIC_PREFIXES = ("/auth", "/health", "/static", "/mein-plan")


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """Erzwingt Login ausserhalb der PUBLIC_PREFIXES und sperrt Azubis auf /mein-plan.

    auth_mode wird bewusst bei JEDEM Request aus settings gelesen (nicht beim
    Modulimport gecacht), damit Tests den Modus per monkeypatch umschalten
    koennen und ein spaeterer Config-Reload ohne Neustart wirkt.

    WICHTIG (Reihenfolge): Diese Middleware-Funktion muss im Quellcode VOR
    app.add_middleware(SessionMiddleware, ...) registriert werden. Starlette
    baut den Middleware-Stack so, dass die zuletzt registrierte Middleware
    aussen liegt (zuerst ausgefuehrt wird) -- SessionMiddleware muss also
    aussen liegen (spaeter registriert werden), sonst ist request.session an
    dieser Stelle noch nicht verfuegbar (AssertionError).
    """
    if settings.auth_mode == "off":
        request.state.current_user = CurrentUser(upn="test@local", name="Test Admin", rolle="admin")
        return await call_next(request)

    path = request.url.path
    if path.startswith(PUBLIC_PREFIXES) or path == "/favicon.ico":
        request.state.current_user = user_from_session(request)
        return await call_next(request)

    user = user_from_session(request)
    if user is None:
        return RedirectResponse("/auth/login", status_code=303)

    if user.rolle == "azubi":
        session_data = request.session.get(SESSION_KEY) or {}
        share_token = session_data.get("share_token")
        if not share_token:
            return RedirectResponse("/auth/login", status_code=303)
        return RedirectResponse(f"/mein-plan/{share_token}", status_code=303)

    request.state.current_user = user
    return await call_next(request)


# https_only haengt am auth_mode: Starlette prueft NICHT die eingehende
# Verbindung, sondern setzt bei https_only=True lediglich das Secure-Flag auf
# das Session-Cookie. Hinter dem TLS-terminierenden Ingress (Browser sieht
# https) ist das genau richtig und verhindert, dass das Cookie je ueber
# Klartext-HTTP mitgesendet wird. Lokal (dev/off, http://localhost bzw.
# TestClient http://testserver) muss das Flag aus bleiben, sonst wird das
# Cookie nicht uebertragen.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.auth_mode == "oidc",
)

app.include_router(auth.router)
app.include_router(overview.router)
app.include_router(jahreswechsel.router)
app.include_router(auto_plan.router)
app.include_router(imports.import_page_router)
app.include_router(imports.router)
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
