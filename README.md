# Wilbeth

Internes Tool zur Einsatzplanung der IT-Auszubildenden bei der grenke digital GmbH.

Ersetzt die bisherige Excel-basierte Planung. Verarbeitet personenbezogene Daten — laeuft ausschliesslich im internen Firmennetz und nutzt **keine** externen KI-APIs.

Stand: Sprint 5 (Polish & Azubi-View). Vollstaendiger Verlauf in [CHANGELOG.md](CHANGELOG.md).

## Tech-Stack

- **Python 3.13+** / **FastAPI**
- **SQLModel** (Pydantic + SQLAlchemy)
- **SQLite** (Entwicklung) / PostgreSQL (Produktion, geplant)
- **Jinja2 + HTMX** (kein Build-Schritt, kein Node.js) + etwas Vanilla-JS
- **Alembic** fuer DB-Migrationen
- **pytest** fuer Tests

## Voraussetzungen

- Python 3.13 oder neuer (`python --version`)
- Windows (PowerShell) oder Linux/macOS (Bash) — beide funktionieren
- Kein Node.js, keine Datenbank-Installation noetig (SQLite ist eingebaut)

## Setup (Erstinstallation)

```powershell
# 1. Virtuelle Umgebung anlegen und aktivieren
python -m venv .venv
.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate

# 2. Abhaengigkeiten installieren
pip install -r requirements.txt

# 3. Datenbank-Schema anlegen
alembic upgrade head

# 4. Beispieldaten laden
python -m seed.seed

# 5. Server starten
uvicorn app.main:app --reload
```

Danach laeuft die App auf <http://127.0.0.1:8000> — Startseite leitet auf `/overview` (Matrix-Ansicht) um.

> **Tipp:** Ist die venv aktiviert (Prompt zeigt `(.venv)`), genuegen `python` und `uvicorn`.
> Ohne Aktivierung den venv-Python explizit aufrufen: `.venv\Scripts\python.exe -m uvicorn app.main:app --reload`.

## Seed zuruecksetzen / neu befuellen

Der Seed ist **idempotent**: Er bricht ab, wenn schon ein Lehrjahr existiert. Fuer einen frischen Stand die DB loeschen und neu aufbauen:

```powershell
# WICHTIG: Laufenden Server vorher stoppen (haelt sonst die DB-Datei gesperrt)
Remove-Item wilbeth.db -Force
alembic upgrade head
python -m seed.seed
```

Der Seed legt an: 2 Lehrjahre (2025-2026, 2026-2027), 12 Schulferien, 6 Klassen, 12 Abteilungen, 20 Trainees (13 Azubis + 7 DH-Studenten) und realistische Einsaetze fuer 2025-2026.

## Tests

```powershell
python -m pytest          # alle Tests
python -m pytest -q       # kompakt
python -m pytest tests/test_conflict_checker.py -v   # einzelne Datei
```

| Testdatei | Deckt ab |
|---|---|
| `test_conflict_checker.py` | Konflikt-Erkennung (Schul-/Ferien-/Doppelbelegung) |
| `test_assignments_range.py` | KW-Range, Eingabe-Hierarchie, Jahreswechsel |
| `test_overview_filters.py` | Matrix: Klassen- & Abteilungs-Filter, Datums-Header |
| `test_trainee_detail.py` | Trainee-Detailseite, Konflikt-Highlight |
| `test_cell_endpoints.py` | Inline-Cell-Edit (edit/save/delete + OOB-Zaehler) |

Tests laufen gegen eine In-Memory-SQLite (StaticPool) und beruehren `wilbeth.db` nicht.

## Datenbank inspizieren

1. **DB Browser for SQLite** (<https://sqlitebrowser.org/>) — `wilbeth.db` oeffnen, "Browse Data".
2. **VS Code Extension** "SQLite Viewer" — DB-Datei im Editor anklicken.
3. **Python-REPL**:

```python
from sqlmodel import Session, select
from app.database import engine
from app.models import Trainee
with Session(engine) as s:
    for t in s.exec(select(Trainee)).all():
        print(t.vorname, t.nachname, t.rolle)
```

## Migrationen

```powershell
alembic revision --autogenerate -m "kurze beschreibung"   # nach Modell-Aenderung
alembic upgrade head                                       # anwenden
alembic downgrade -1                                       # zuruecknehmen
```

Auto-generierte Skripte enthalten `import sqlmodel` (in `script.py.mako` vorbereitet).

## Architektur

| Schicht | Verzeichnis | Aufgabe |
|---|---|---|
| **Routers** | `app/routers/` | HTTP-Endpunkte, ein Modul pro Bereich (overview, trainees, assignments, school_plans, …) |
| **Models** | `app/models/` | SQLModel-Tabellen, eine Datei pro Entity |
| **Services** | `app/services/` | Domaenenlogik (`conflict_checker.py`) |
| **Utils** | `app/utils/` | KW-/Datums-Arithmetik (`kw.py`) |
| **Templates** | `app/templates/` | Jinja2-Views, Partials in `_partials/` |
| **Static** | `app/static/` | `style.css`, lokales `htmx.min.js` |
| **Migrationen** | `alembic/` | Schema-Versionierung |
| **Seed** | `seed/` | Beispieldaten |

Patterns: PRG (Post-Redirect-Get) mit Flash via `?msg=…`, HTMX fuer Inline-Edits und Loeschen ohne Seitenwechsel, ISO-8601-Kalenderwochen durchgehend (`app/utils/kw.py`).

## Domaenenmodell

| Tabelle | Zweck |
|---|---|
| `schoolyear` | Lehrjahr (z. B. "2025-2026"), KW-Bereich KW36–KW35 |
| `trainee_class` | Klasse (z. B. "FISI 2. LJ"), Berufsschule, Unterrichts-Typ |
| `school_holiday` | Schulferien pro Lehrjahr |
| `school_plan` | Verbindung Klasse + Lehrjahr |
| `school_plan_week` | Einzelne BS-/Uni-Wochen pro Plan |
| `trainee` | Auszubildende, DH-Studis, Praktikanten, Umschueler |
| `department` | Abteilung mit Code, Kategorie, Mehrfachbelegung-Flag |
| `assignment` | Ein Trainee in einer KW: ABTEILUNG, URLAUB, BS, UNI, FREI |

Wichtige Constraints:
- `assignment.UNIQUE(trainee_id, kw, jahr)` — eine KW pro Person, ein Eintrag.
- `school_plan.UNIQUE(klasse_id, schoolyear_id)` — ein Plan pro Klasse pro Jahr.
- `school_plan_week.UNIQUE(plan_id, kw, jahr)` — keine doppelten Wochen pro Plan.

## Konflikt-Logik

Wilbeth blockiert nie hart (Ausnahme s. u.) — es zeigt Warnungen, die Planerin entscheidet.

1. **Schul-Konflikt**: ABTEILUNG/URLAUB in einer KW, in der die Klasse laut SchoolPlan in BS/UNI ist.
2. **Ferien-Konflikt**: BS-/UNI-Eintrag faellt auf eine Schulferien-Woche.
3. **Doppelbelegung**: Mehrere Personen in derselben Abteilung/KW (ausser `erlaubt_mehrfachbelegung = True`, z. B. BA).

Eingabe-Hierarchie beim Anlegen (`BERUFSSCHULE = UNI` > `URLAUB` > `ABTEILUNG` > `FREI`): Hoehere Stufe ueberschreibt niedrigere automatisch, gleiche Stufe fragt per Bestaetigungsseite nach.

## Troubleshooting

| Problem | Ursache / Loesung |
|---|---|
| `No module named 'sqlmodel'` / `uvicorn` | venv nicht aktiv. `.venv\Scripts\Activate.ps1` oder venv-Python direkt nutzen. |
| `Der Prozess kann nicht auf die Datei wilbeth.db zugreifen` | Server laeuft noch und sperrt die DB. Server stoppen, dann loeschen. |
| `Datenbank enthaelt bereits Lehrjahr …` | Seed ist idempotent. Erst `wilbeth.db` loeschen (s. „Seed zuruecksetzen"). |
| `no such table: …` beim Seed | Schema fehlt. `alembic upgrade head` vor dem Seed laufen lassen. |
| Server startet, aber keine Daten | Seed vergessen: `python -m seed.seed`. |

## Offene Punkte

- DHBW Uni-Phasen: vollstaendiger Jahresrhythmus muss noch dokumentiert werden
- Datenschutzkonzept: Abstimmung mit DSB grenke digital steht aus
- Auth/SSO: Anbindung an bestehendes System (SAP, Active Directory) — User sind dort bereits angelegt
- Schulferien 2026-2027: aktuell BW-Schaetzwerte, mit offiziellem Kalender abgleichen
