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
# 1. Virtuelle Umgebung anlegen und aktivieren (im Repo-Root)
python -m venv .venv
.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate

# 2. In den App-Ordner wechseln — der App-Code liegt jetzt unter src/
cd src

# 3. Abhaengigkeiten installieren
pip install -r requirements.txt

# 4. Datenbank-Schema anlegen
alembic upgrade head

# 5. Beispieldaten laden
python -m seed.seed

# 6. Server starten
uvicorn app.main:app --reload
```

Danach laeuft die App auf <http://127.0.0.1:8000> — Startseite leitet auf `/overview` (Matrix-Ansicht) um.

> **Wichtig (Repo-Struktur):** Der gesamte App-Code liegt seit dem Deployment-Umbau unter **`src/`** (App + Dockerfile = Image-Kontext). **Alle** Kommandos in dieser README (`alembic`, `python -m seed…`, `pytest`, `uvicorn`) werden **aus dem `src/`-Verzeichnis** ausgefuehrt. Die k8s-Manifeste liegen unter `k8s/`, die Pipeline in `azure-pipelines.yml`.

> **Tipp:** Ist die venv aktiviert (Prompt zeigt `(.venv)`), genuegen `python` und `uvicorn`.
> Ohne Aktivierung den venv-Python explizit aufrufen (aus `src/`): `..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload`.

> **„Wie starte ich die Datenbank?"** — Lokal gibt es **keinen** separaten DB-Server. Die Datenbank ist die Datei `src/wilbeth.db` (SQLite). `alembic upgrade head` legt das Schema darin an, `python -m seed.seed` fuellt Beispieldaten, und die App (uvicorn) liest die Datei direkt. Ein echter Server (PostgreSQL) kommt erst beim Kubernetes-Deployment ins Spiel.

> **„Wo sehe ich, wo ein Azubi schon war?"** — In der Uebersicht (`/overview`) unter dem Azubi-Namen als „War-schon-in"-Chips, und beim Klick auf eine Zelle als Warnhinweis im Dialog. Das erscheint nur, wenn der Azubi bereits ABTEILUNG-Einsaetze hat — also erst nach dem Seed bzw. nach dem Anlegen von Einsaetzen.

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

Aktuell **130 Tests**, alle gruen.

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
| **Routers** | `src/app/routers/` | HTTP-Endpunkte, ein Modul pro Bereich (overview, trainees, assignments, school_plans, …) |
| **Models** | `src/app/models/` | SQLModel-Tabellen, eine Datei pro Entity |
| **Services** | `src/app/services/` | Domaenenlogik (`conflict_checker.py`, `school_sync.py`) |
| **Utils** | `src/app/utils/` | KW-/Datums-Arithmetik (`kw.py`) |
| **Templates** | `src/app/templates/` | Jinja2-Views, Partials in `_partials/` |
| **Static** | `src/app/static/` | `style.css`, lokales `htmx.min.js` |
| **Migrationen** | `src/alembic/` | Schema-Versionierung |
| **Seed** | `src/seed/` | Beispieldaten |
| **Deployment** | `k8s/`, `azure-pipelines.yml` | Kustomize-Manifeste + Azure-Pipeline (s. [`k8s/README.md`](k8s/README.md)) |

Patterns: PRG (Post-Redirect-Get) mit Flash via `?msg=…`, HTMX fuer Inline-Edits und Loeschen ohne Seitenwechsel, ISO-8601-Kalenderwochen durchgehend (`src/app/utils/kw.py`).

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

### Gesamtablauf (Kustomize – kein Helm)

```
GitHub (main-Push) ──► Azure-DevOps-Repo ──► azure-pipelines.yml
  Stage 1 Build:  Docker-Image aus src/ bauen ──► Harbor-Registry
  Stage 2 Deploy: replacetokens (Secret + Image-Tag)
                  └─ kubectl kustomize k8s/overlays/test ──► kubectl apply ──► Rollout-Checks
  Ziel: Cluster-Namespace <NAMESPACE>; PostgreSQL laeuft als eigenes Deployment im selben Namespace.
```

### Struktur

- `src/` — App + `Dockerfile` (= Docker-Build-Kontext)
- `k8s/base/` — `configmap.yaml`, `secret.yaml` (nur `{{dbPassword}}`-Token), `pvc.yaml`, `deployment.wilbeth.yaml`, `deployment.postgres.yaml`, `service.*.yaml`, `kustomization.yaml`
- `k8s/overlays/test/` — `ingress.yaml` (+ cert-manager `Certificate`), `kustomization.yaml`
- `azure-pipelines.yml` — Build- + Deploy-Stage

### Geheimnisse & Platzhalter

- **Secrets stehen nie im Git.** `k8s/base/secret.yaml` enthaelt nur den Token `{{dbPassword}}`; der Azure-Task `replacetokens@6` setzt den echten Wert beim Deploy aus einer **Variable Group** ein. Der Image-Tag (`{{imageTag}}`) wird genauso gesetzt.
- **`<<<…>>>`-Platzhalter** (Namespace, Harbor-Projekt, Host, Service-Connection, Environment, Responsible-Team-Mail) muessen **einmalig** in den Dateien ersetzt werden — vollstaendige Liste + Ansprechpartner in **[`k8s/README.md`](k8s/README.md)**. Die Deploy-Pipeline bricht ab, falls im gerenderten Manifest noch `{{…}}` oder `<<<…>>>` stehen.

### PostgreSQL

Laeuft als eigenes Deployment im Cluster (`k8s/base/deployment.postgres.yaml` + `pvc.yaml`, StorageClass `longhorn`). Die App verbindet sich ueber die `DATABASE_URL` aus dem Secret:

```
postgresql+psycopg://wilbeth:<dbPassword>@postgres:5432/wilbeth
```

### Sicherheit / TLS

Der Pod spricht **HTTP** auf Port 8080 (non-root, UID 1654). TLS terminiert der **nginx-Ingress**; das Zertifikat stellt **cert-manager** (ClusterIssuer `keyfactor-command-issuer`) fuer den Host aus.

### Lokales Docker-Testing mit Postgres (optional)

```bash
cd src
docker compose --profile postgres up -d --build   # App auf Port 8081, Postgres intern
docker compose exec wilbeth-pg python -m seed.seed
```

### Seed / Wartung im Cluster

```bash
kubectl exec -n <NAMESPACE> deploy/wilbeth -- python -m seed.seed
kubectl exec -n <NAMESPACE> deploy/wilbeth -- python -m seed.add_fisi_plan
kubectl exec -n <NAMESPACE> deploy/wilbeth -- python -m seed.clean   # Vorsicht: leert Daten
```

### Weitergehende Dokumentation

- `k8s/README.md` — Platzhalter-Tabelle, Reihenfolge, Secret-Handling
- `pipelines/README.md` — Service Connections anlegen, Pipeline-Ablauf

## Offene Punkte

- DHBW Uni-Phasen: vollstaendiger Jahresrhythmus muss noch dokumentiert werden
- Datenschutzkonzept: Abstimmung mit DSB grenke digital steht aus
- Auth/SSO: Anbindung an bestehendes System (SAP, Active Directory) — User sind dort bereits angelegt
- Schulferien 2026-2027: aktuell BW-Schaetzwerte, mit offiziellem Kalender abgleichen
