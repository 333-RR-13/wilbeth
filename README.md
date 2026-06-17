# Wilbeth

Internes Tool zur Einsatzplanung der IT-Auszubildenden bei der grenke digital GmbH.

Ersetzt die bisherige Excel-basierte Planung. Verarbeitet personenbezogene Daten — laeuft ausschliesslich im internen Firmennetz und nutzt **keine** externen KI-APIs.

Vollstaendiger Verlauf in [CHANGELOG.md](CHANGELOG.md).

## Funktionsumfang

- **Stammdaten-CRUD**: Lehrjahre, Klassen, Abteilungen, Trainees, Schulferien, Schulplaene. Tabellenzeilen sind klickbar.
- **Matrix-Uebersicht** (Trainee × KW) mit KW-/Datums-Header, Heute-Markierung, Inline-Zell-Edit und Filtern (Klasse, Abteilung).
- **Konflikt-Erkennung** (Schul-/Ferien-/Doppelbelegung) inkl. „Warum?"-Erklaerung im Panel und im Zell-Dialog.
- **Einsatz-Anlage** fuer einzelne KW oder KW-Bereich, mit Eingabe-Hierarchie (BS/UNI > Urlaub > Abteilung > Frei).
- **Unterrichts-Typen**: Blockunterricht (FISI, FIAE, DHBW, BWL) **und** Wochentag-Schule (Buerokaufleute, feste Schultage je Woche).
- **Automatische Schul-Einsaetze**: Schulplan-Wochen werden fuer alle Klassenmitglieder als `BERUFSSCHULE`/`UNI`-Einsaetze (`source=AUTO`) materialisiert und synchron gehalten.
- **Abteilungs-Historie**: „War-schon-in"-Chips in der Planungszeile + weiche Wiederholungs-Warnung beim Zuweisen einer bereits besuchten Abteilung (kein Block).
- **Azubi-Self-Service** (Token-Link `/mein-plan/{token}`): eigener Plan, Klassen-Matrix, Urlaub selbst eintragen, Wuensche, ICS-Kalender-Export.
- **„Ueber Wilbeth"**-Erzaehlseite.
- **Deployment**: Container (Dockerfile) + Kubernetes-Manifeste + Azure-DevOps-Pipelines (Harbor) mit PostgreSQL — siehe „Deployment".

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

Der Seed legt an: 2 Lehrjahre (2025-2026, 2026-2027), 12 Schulferien, **12 Klassen** (FISI/FIAE 1.–3. LJ, DHBW WI/Cybersecurity, Buero 1.–3. LJ, BWL), **19 Abteilungen** und **26 Trainees** (17 Azubis inkl. 4 Buerokaufleute, 9 DH-Studenten inkl. 2 BWL) mit realistischen Einsaetzen fuer 2025-2026.

## Wartungs-Skripte

```powershell
python -m seed.clean          # leert alle Daten AUSSER Klassen & Abteilungen
python -m seed.add_fisi_plan  # legt Lehrjahr 2025-2026 (falls noetig) + FISI-Schulplaene an
python -m seed.sync_school    # Backfill: erzeugt AUTO-Schul-Einsaetze fuer alle Klassenmitglieder
```

Hinweis: Nach `seed.clean` **nicht** den vollen `seed.seed` laufen lassen — er wuerde Klassen/Abteilungen erneut anlegen und an den Unique-Constraints scheitern.

## Tests

```powershell
python -m pytest          # alle Tests
python -m pytest -q       # kompakt
python -m pytest tests/test_conflict_checker.py -v   # einzelne Datei
```

Aktuell **107 Tests**, alle gruen.

| Testdatei | Deckt ab |
|---|---|
| `test_conflict_checker.py` | Konflikt-Erkennung (Schul-/Ferien-/Doppelbelegung) |
| `test_conflicts_ui.py` | Konflikt-Panel & „Warum?"-Erklaerung |
| `test_assignments_range.py` | KW-Range, Eingabe-Hierarchie, Jahreswechsel |
| `test_overview_filters.py` | Matrix: Klassen-/Abteilungs-Filter, Datums-Header |
| `test_cell_endpoints.py` | Inline-Cell-Edit (edit/save/delete + OOB-Zaehler) |
| `test_school_plan_chips.py` | Schulblock-Anzeige in den Matrizen |
| `test_school_sync.py` | Automatische AUTO-Schul-Einsaetze (anlegen/synchronisieren) |
| `test_dept_history.py` | Abteilungs-Historie (War-schon-in + Wiederholungs-Warnung) |
| `test_tage_fest.py` | Wochentag-Schule (Buerokaufleute), Klassen-Matrix |
| `test_trainee_detail.py` | Trainee-Detailseite, Konflikt-Highlight |
| `test_klassen_detail.py` | Klassen-Bearbeiten + Mitglieder-Zuweisung |
| `test_share.py` | Azubi-Self-Service (Token, Urlaub, Wuensche, ICS) |
| `test_about.py` | „Ueber Wilbeth"-Seite |
| `test_health.py` | `/health`-Endpoint (Docker) |

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
| **Services** | `app/services/` | Domaenenlogik (`conflict_checker.py`, `school_sync.py`) |
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
| `trainee_class` | Klasse, Berufsschule, Unterrichts-Typ (BLOCK_FEST/DH_PHASEN/TAGE_FEST); bei TAGE_FEST: Schultage + Halbtag |
| `school_holiday` | Schulferien pro Lehrjahr |
| `school_plan` | Verbindung Klasse + Lehrjahr |
| `school_plan_week` | Einzelne BS-/Uni-Wochen pro Plan |
| `trainee` | Auszubildende, DH-Studis, Praktikanten, Umschueler; `share_token` (Self-Service-Link), `wunsch_notiz` |
| `trainee_wish` | Abteilungs-Wunsch eines Trainees mit Prioritaet (1–3) |
| `department` | Abteilung mit Code, Kategorie, Mehrfachbelegung-Flag |
| `assignment` | Ein Trainee in einer KW: ABTEILUNG/URLAUB/BS/UNI/FREI; `source` = MANUAL/AUTO/SELBST/SAP |

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

## Deployment (Kubernetes / Azure DevOps / Harbor)

> **Sicherheitshinweis:** Wilbeth hat **keine Authentifizierung**. Admin- und Trainee-Daten sind fuer jeden offen, der den Port erreicht. Die App **nur im abgeschirmten internen Netz** oder **hinter einem authentifizierenden Reverse-Proxy** betreiben — niemals direkt ins Internet stellen.
>
> **Datenschutz:** Das Datenschutzkonzept (DSB grenke digital) muss vor dem Einsatz mit echten personenbezogenen Daten abgesegnet sein.

### Gesamtablauf

```
GitHub (main-Push)
  └─► Azure DevOps Build-Pipeline  (pipelines/azure-pipelines-build.yml)
        ├─ Tests (pytest)           — CI-Gate; kein Image ohne gruene Tests
        └─ Docker buildAndPush      — Image → Harbor-Registry
              └─► Deploy-Pipeline  (pipelines/azure-pipelines-deploy.yml)
                    └─ kubectl apply → Cluster tools-test (Namespace <NAMESPACE>)
                                    → spaeter: tools-prod
```

### Voraussetzungen (vom Nutzer zu organisieren)

- **Harbor-Zugriff**: Harbor-Projekt anlegen, Serviceaccount mit Push-Rechten.
- **Azure DevOps Repo/Projekt**: Pipeline-Dateien aus `pipelines/` dort eintragen.
- **3 Service Connections** in Azure DevOps (Project Settings → Service Connections):
  1. **GitHub** — Zugriff auf `333-RR-13/wilbeth` (OAuth oder PAT).
  2. **Harbor** — Docker Registry, URL `https://<HARBOR_REGISTRY>`, Harbor-Credentials.
  3. **Kubernetes** — Kubeconfig oder Service-Account-Token fuer Namespace `<NAMESPACE>` auf `tools-test`.
- **Namespace + RBAC** auf `tools-test`: Namespace anlegen, ServiceAccount mit `kubectl apply`-Rechten.

### Platzhalter-Tabelle

Alle `<PLACEHOLDER>`-Werte muessen vor dem ersten Pipeline-Lauf gefuellt werden:

| Platzhalter | Datei(en) | Was eintragen |
|---|---|---|
| `<NAMESPACE>` | alle k8s/, deploy-Pipeline | Kubernetes-Namespace, z. B. `tools-test` |
| `<DB_PASSWORD>` | `k8s/secret.example.yaml` | Sicheres Passwort fuer Postgres-User `wilbeth` |
| `<STORAGE_CLASS>` | `k8s/postgres.yaml` | StorageClass des Clusters (beim Cluster-Admin erfragen) |
| `<HARBOR_REGISTRY>` | `k8s/deployment.yaml`, Pipelines | Hostname der Harbor-Registry, z. B. `harbor.example.com` |
| `<HARBOR_PROJECT>` | `k8s/deployment.yaml`, Pipelines | Harbor-Projektname, z. B. `wilbeth` |
| `<IMAGE_TAG>` | `k8s/deployment.yaml` | Wird von der Deploy-Pipeline automatisch auf `$(Build.BuildId)` gesetzt |
| `<INGRESS_HOST>` | `k8s/ingress.yaml` | Hostname der App, z. B. `wilbeth.tools.example.com` |
| `<INGRESS_CLASS>` | `k8s/ingress.yaml` | Ingress-Controller-Name (`nginx`, `traefik`, …) |
| `<GITHUB_SERVICE_CONNECTION>` | Build-Pipeline | Name der Azure DevOps Service Connection zu GitHub |
| `<HARBOR_SERVICE_CONNECTION>` | Build-Pipeline | Name der Azure DevOps Service Connection zu Harbor |
| `<K8S_SERVICE_CONNECTION>` | Deploy-Pipeline | Name der Azure DevOps Service Connection zum Cluster |
| `<BUILD_PIPELINE_ID>` | Deploy-Pipeline | Name/ID der Build-Pipeline in Azure DevOps |

### PostgreSQL

Standardmaessig wird ein PostgreSQL-Pod via `k8s/postgres.yaml` im Cluster deployt (StatefulSet mit PVC).

Alternativ: Falls die Firma eine **gemanagte PostgreSQL** bereitstellt (z. B. Azure Database for PostgreSQL), `k8s/postgres.yaml` weglassen und `DATABASE_URL` im Secret direkt auf die externe DB zeigen.

Verbindungs-URL Format (SQLAlchemy / psycopg v3):
```
postgresql+psycopg://wilbeth:<DB_PASSWORD>@wilbeth-db:5432/wilbeth
```

### Reihenfolge beim Erst-Deploy

1. **Secret anlegen** (niemals committen — nur lokal bearbeiten und mit kubectl anwenden):
   ```bash
   cp k8s/secret.example.yaml /tmp/wilbeth-secret.yaml
   # Platzhalter in /tmp/wilbeth-secret.yaml fuellen
   kubectl apply -f /tmp/wilbeth-secret.yaml -n <NAMESPACE>
   rm /tmp/wilbeth-secret.yaml
   ```
2. **PostgreSQL deployen** (oder weglassen bei externer DB):
   ```bash
   kubectl apply -f k8s/postgres.yaml -n <NAMESPACE>
   ```
3. **Build-Pipeline** in Azure DevOps einrichten und einmal ausfuehren (push auf `main` genuegt).
4. **Deploy-Pipeline** einrichten — wird automatisch nach der Build-Pipeline getriggert.
5. **Seed einmalig ausfuehren** (nur beim ersten Mal, nach erfolgreichem Deploy):
   ```bash
   kubectl exec -n <NAMESPACE> deploy/wilbeth -- python -m seed.seed
   ```

### Lokales Docker-Testing mit Postgres (optional)

```bash
# Postgres-Profil starten (App auf Port 8001, Postgres intern)
docker compose --profile postgres up -d --build

# Seed
docker compose exec wilbeth-pg python -m seed.seed
```

### Seed / Wartung im Cluster

```bash
# Beispieldaten laden (einmalig)
kubectl exec -n <NAMESPACE> deploy/wilbeth -- python -m seed.seed

# FI-SI-Plan nachtragen
kubectl exec -n <NAMESPACE> deploy/wilbeth -- python -m seed.add_fisi_plan

# Daten leeren (Vorsicht!)
kubectl exec -n <NAMESPACE> deploy/wilbeth -- python -m seed.clean
```

### Weitergehende Dokumentation

- `k8s/README.md` — Platzhalter-Tabelle, Reihenfolge, Secret-Handling
- `pipelines/README.md` — Service Connections anlegen, Pipeline-Ablauf

## Offene Punkte

- DHBW Uni-Phasen: vollstaendiger Jahresrhythmus muss noch dokumentiert werden
- Datenschutzkonzept: Abstimmung mit DSB grenke digital steht aus
- Auth/SSO: Anbindung an bestehendes System (SAP, Active Directory) — User sind dort bereits angelegt
- Schulferien 2026-2027: aktuell BW-Schaetzwerte, mit offiziellem Kalender abgleichen
