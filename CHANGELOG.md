# Changelog

Alle nennenswerten Aenderungen am Projekt Wilbeth.

Format orientiert an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unreleased]

### Klassen-Mitgliedschaft pro Lehrjahr + Jahreswechsel

- Azubis werden **pro Lehrjahr** einer Klasse zugeordnet (neue Tabelle
  `TraineeClassMembership`, Migration `0002membership`). `school_sync`, Übersicht
  und Konfliktprüfung verwenden die Klasse des jeweiligen Lehrjahrs (Fallback auf
  `Trainee.klasse_id`, damit bestehende Azubis weiter laufen).
- Klassen haben eine **„nächste Klasse"** (`next_class_id`); ein globaler
  **Jahreswechsel** (`/jahreswechsel`) übernimmt mit Vorschau alle Azubis ins nächste
  Lehrjahr und synchronisiert die Schulwochen (`resync_all`). Trainee-Formular mit
  Lehrjahr + Klasse; Klassen-Mitglieder pro Lehrjahr verwaltbar.

### Auto-Plan & Import als eigene Reiter

- **Auto-Plan** und **Einsatz-Import** aus der Einsatzübersicht herausgelöst in je
  einen eigenen Sidebar-Reiter (`/auto-plan`, `/import`); die Übersicht ist wieder
  schlank wie zuvor. Auto-Plan-Logik (`auto_plan.py`) und Import (`importer.py`)
  bleiben unverändert — nur Routen/Seiten/Navigation umgestellt. Schulplan-Import
  bleibt kontextuell auf der Schulplan-Seite.

### Auto-Plan & Daten-Import

- **Auto-Plan**: Button + Checkboxen in der Einsatzübersicht. Weist ausgewählte
  Azubis in ihren freien Wochen automatisch Abteilungen zu — in Blöcken nach
  Wunsch-Priorität (`TraineeWish`), Block-Länge einstellbar (Default 4). Vermeidet
  Doppelbelegung (je `erlaubt_mehrfachbelegung`) und meidet bereits besuchte
  Abteilungen weich. Vorschau vor dem Übernehmen; nur freie Wochen, `source=AUTO`;
  mehrfach ausführbar. (`app/services/auto_plan.py`)
- **Daten-Import**: „Import"-Button auf der Schulplan-Seite (Schulplan-Wochen) und in
  der Übersicht (vergangene Einsätze). Eingabe per Excel-Copy (Tab) oder CSV-Upload
  (Tab/Semikolon/Komma automatisch erkannt), mit Vorschau + Validierung. Azubis per
  „Nachname, Vorname", Abteilungen per Code. Bestehende Einträge werden übersprungen,
  importierte Einsätze bekommen `source=IMPORT`. (`app/services/importer.py`)

### Overview: Wochen-Breite einstellbar

- **KW-Fenster-Dropdown**: Auf der Einsatzübersicht lässt sich über ein neues
  Dropdown wählen, wie viele Kalenderwochen der mittlere Tabellenteil zeigt
  (4 / 8 / 12 / 16 / 26 Wochen oder „Alle Wochen"). Das Fenster beginnt bei der
  aktuellen KW (sonst am Lehrjahresanfang); ohne Auswahl wird wie bisher das
  ganze Lehrjahr angezeigt. Umsetzung in `app/routers/overview.py` (Query-Param
  `wochen`, Slicing der Wochenliste) und `app/templates/overview/matrix.html`
  (Dropdown in der Filterleiste, `onchange`-Submit).

### Overview-Matrix: volle Breite, vereinheitlichte Chips

- **Tabelle nutzt die volle Seitenbreite**: Die Einsatzübersicht ist nicht mehr
  auf 1100px begrenzt (`content-inner--wide`); die Wochen-Spalten verteilen sich
  über `width: 100%` über die ganze Breite.
- **„Bereits eingeplant"-Spalte ohne Umbruch**: Die Abteilungs-Chips stehen jetzt
  immer in einer Zeile (`flex-wrap: nowrap`), die Spalte wird so breit wie nötig.
- **Urlaub-Chip**: Das Kürzel „BLK" heißt jetzt „U", die Legende „Urlaub"
  (vorher „Blocker (Urlaub/Frei)").
- **Schulwochen vereinheitlicht**: Die separate, ausgeblasste „Schulwoche
  (Klasse)"-Darstellung (`cell-auto`) und die hellblaue Zell-Hintergrund-
  markierung (`mc-school`) wurden entfernt. Schulwochen erscheinen jetzt als
  normaler, solider BS/HS-Chip (mit `title="laut Klassen-Schulplan"`) — auch in
  den Azubi-Ansichten (Mein Plan / Meine Klasse). Tests entsprechend angepasst.

### Deployment auf Kustomize umgestellt (noch nicht committet)

- **Helm-Ansatz verworfen**: Statt des `helm-generic`-Charts wird – wie das
  Referenz-Repo der AI Platform – ein **Kustomize**-Setup verwendet. Alte
  Artefakte entfernt (`helm/`, altes `k8s/` mit losen Manifesten, `pipelines/`).
- **App nach `src/` verschoben**: `app/`, `alembic/`, `seed/`, `tests/`,
  `requirements.txt`, `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.yml`
  liegen jetzt unter `src/` (= Docker-Build-Kontext). Befehle laufen aus `src/`.
- **Dockerfile/Entrypoint auf schlichtes HTTP** (Port 8080) vereinfacht: kein
  TLS im Pod mehr (das übernimmt der Ingress), `openssl`/`WILBETH_TLS`/8443
  entfernt. Bleibt non-root (UID 1654), HEALTHCHECK über HTTP.
- **Neue `k8s/`-Struktur**: `k8s/base/` (configmap, secret mit `{{dbPassword}}`-
  Token, pvc, `deployment.wilbeth`, `deployment.postgres`, services,
  kustomization) und `k8s/overlays/test/` (ingress + cert-manager `Certificate`
  mit ClusterIssuer `keyfactor-command-issuer`). PostgreSQL läuft selbst im
  Cluster (PVC `longhorn`).
- **Neue `azure-pipelines.yml`**: Stage 1 baut das Image aus `src/` und pusht es
  nach Harbor; Stage 2 ersetzt Tokens via `replacetokens@6` (Secret + Image-Tag),
  rendert Kustomize und führt `kubectl apply` mit Rollout-Checks aus.
  Firmenspezifische Unbekannte als `<<<…>>>`-Platzhalter; Details in `k8s/README.md`.
- README-Deployment-Abschnitt und Architektur-Tabelle entsprechend aktualisiert.

### Postgres-Härtung & Deployment-Verbesserungen

- **Migrationen zusammengefasst**: Die bisherigen 5 Alembic-Migrationen
  (`cf3e27b74779` → `f5db6557783c` → `a7c1e9f4b2d8` → `b3f2a9c5d1e7` →
  `c4a8e1f2d3b9`) wurden durch eine einzige initiale Migration
  `0001squashed` ersetzt. Alle `sa.Enum`-Spalten verwenden jetzt
  `native_enum=False` — auf PostgreSQL werden sie als `VARCHAR` statt als
  nativer PG-ENUM-Typ angelegt. Damit entfallen künftige `ALTER TYPE … ADD
  VALUE`-Migrationen bei neuen Enum-Werten, und der komplette
  Enum-Wertestand (`TAGE_FEST` bei `UnterrichtsTyp`; `SELBST`, `SAP` bei
  `AssignmentSource`) ist von Anfang an auf einem frischen PostgreSQL
  verfügbar.
- **imagePullSecret-Platzhalter** (`k8s/deployment.yaml`): Unter
  `spec.template.spec` wurde `imagePullSecrets: [{name: <HARBOR_PULL_SECRET>}]`
  ergänzt (mit Kommentar, dass es nur bei fehlendem globalem Cluster-Pull-
  Credential benötigt wird). `k8s/README.md` listet den neuen Platzhalter
  und enthält eine Kurzanleitung zur Secret-Erstellung via
  `kubectl create secret docker-registry`.
- **`.gitattributes`**: Neue Datei im Repo-Root normalisiert Zeilenenden auf
  LF (`* text=auto eol=lf`) und markiert Binärdateien
  (`*.png`, `*.ico`, `*.zip`, `*.min.js`). Verhindert CRLF-Warnungen und
  stellt konsistente Zeilenenden im Linux-Container sicher.

### Matrix-Darstellung: Chip-Overhaul (Sprint 8)

- **Abteilungsfarben**: `Department`-Modell erhält Feld `farbe` (hex, Default `#9CA3AF`). Alembic-Migration `c4a8e1f2d3b9` (down_revision `b3f2a9c5d1e7`) fügt Spalte hinzu und setzt bekannte Abteilungsfarben per Data-Migration. Abteilungsformular (`departments/form.html`) zeigt `<input type="color">` Feld „Farbe". Router `departments.py` akzeptiert und persistiert `farbe`.
- **BS/HS zusammengefasst (blau)**: BERUFSSCHULE-Assignments zeigen Chip `BS`, UNI-Assignments zeigen `HS` — beide mit CSS-Klasse `.cell-school` (blau, analog bisheriges Berufsschule-Chip). Auto-Chips aus dem Klassenplan ebenfalls BS/HS mit `.cell-auto`.
- **Blocker dunkel „BLK"**: URLAUB und FREI werden als einheitlicher `BLK`-Chip mit CSS-Klasse `.cell-blocker` (dunkel `#374151`, weiße Schrift) dargestellt — beide Typen nicht mehr unterscheidbar.
- **„Bereits eingeplant"-Spalte rechts**: Visited-Departments werden nicht mehr unter dem Namen angezeigt, sondern in einer sticky-right Spalte „Bereits eingeplant" am Ende der Overview-Matrix (`matrix-th-visited`, `matrix-td-visited`).
- **Geteiltes Chip-Macro** `app/templates/_partials/chip.html`: Jinja-Makros `cell_content` und `dept_chip` zentralisieren die Chip-Logik. Eingebunden in `overview/matrix.html`, `_partials/week_matrix.html`, `_partials/cell.html`, `trainees/detail.html`.
- **Color-Utility** `app/utils/colors.py`: `text_color_for(hex)` (Luminanz-basiert) und `department_color_map(depts)` — alle relevanten Router übergeben `dept_colors` ans Template.
- **Seed** `seed/seed.py`: `seed_departments` enthält nun pro Abteilung eine `farbe`.
- **Legends** in `overview/matrix.html`, `share/plan.html`, `share/klasse.html` aktualisiert auf neue Chip-Kategorien.

### Deployment: Kubernetes / Azure DevOps / Harbor (+ PostgreSQL)

- `Dockerfile`: Python 3.13-slim, Layer-Caching fuer `requirements.txt`, SQLite-Daten auf separatem Volume `/data`, Alembic-Migration laeuft automatisch beim Container-Start vor uvicorn, HEALTHCHECK ueber `/health`.
- `.dockerignore`: schliessst `.venv`, Caches, `.git`, Testverzeichnis, `design bib/`, `*.db` und `.env` aus.
- `docker-compose.yml`: Service `wilbeth`, benanntes Volume `wilbeth_data`, `restart: unless-stopped`.
- `/health`-Endpunkt in `app/main.py`: gibt `{"status": "ok"}` zurueck (200), genutzt vom Docker HEALTHCHECK.
- `tests/test_health.py`: prueft GET /health → 200 + `{"status": "ok"}`.
- **Kubernetes-Manifeste** (`k8s/`): App-`Deployment` (1 Replica, Liveness/Readiness auf `/health`), `Service`, `Ingress`, **PostgreSQL-`StatefulSet` + PVC**, Secret-Vorlage (`DATABASE_URL`), `kustomization.yaml` — alles mit Platzhaltern + `k8s/README.md`.
- **Azure-DevOps-Pipelines** (`pipelines/`): Build (Checkout GitHub → `pytest`-Gate → `Docker@2 buildAndPush` nach Harbor) und Deploy (`KubernetesManifest@1` auf den Cluster), je mit README + Platzhaltern.
- **PostgreSQL** als Cluster-DB: `psycopg[binary]` ergaenzt; `app/database.py` setzt `check_same_thread` nur noch fuer SQLite (lokal weiterhin SQLite, im Cluster Postgres via `DATABASE_URL`). Optionales Postgres-Profil in `docker-compose.yml`.
- README: Deployment-Abschnitt auf den k8s/Harbor/Azure-Flow umgestellt — Voraussetzungen (Harbor-Zugang, Azure-Repo, 3 Service Connections, Namespace/RBAC), Platzhalter-Tabelle, **Hinweis: App nur netzintern betreiben bis Auth (SAP/AD) existiert**; DSB-Freigabe vor echten Personendaten erforderlich.

### Abteilungs-Historie pro Azubi

- **„War schon in"-Anzeige**: In der Planungs-Matrix erscheinen neben dem Azubi-Namen kleine Chips der Abteilungen, in denen er bereits einen Einsatz hatte (Tooltip mit vollen Namen).
- **Weiche Wiederholungs-Warnung**: Im Inline-Zell-Dialog wird beim Waehlen einer Abteilung, in der der Azubi schon war, „⚠️ … war bereits in dieser Abteilung" eingeblendet — rein informativ, **kein** Block (zweiter Einsatz bleibt erlaubt). Die aktuell bearbeitete Woche ist von der Pruefung ausgenommen.
- Neuer Helfer `app/services/dept_history.py` (`visited_department_ids`, `visited_departments`); Tests `tests/test_dept_history.py` (15). Gesamt-Suite **107 gruen**.

### AUTO-Einsätze aus Schulplan materialisieren (School-Sync)

- Schulblöcke werden automatisch als AUTO-Einsätze (`source = AUTO`, `typ = BERUFSSCHULE` oder `UNI`) für alle Klassenmitglieder angelegt, sobald eine `SchoolPlanWeek` hinzugefügt wird.
- **Nur leere Wochen**: Ein AUTO-Eintrag entsteht nur, wenn die Zelle (trainee_id, kw, jahr) noch keinen Einsatz enthält. Manuelle Einträge (ABTEILUNG, URLAUB usw.) bleiben unberührt und bleiben als sichtbarer Konflikt erhalten.
- **Synchron halten**: Tritt ein Azubi einer Klasse bei oder verlässt sie, werden ihre AUTO-Schuleinträge sofort angepasst (erstellt bzw. entfernt). Gleiches gilt beim Hinzufügen, Ändern oder Löschen einer `SchoolPlanWeek` sowie beim Löschen eines ganzen Schulplans.
- **Hooks**: `POST /trainees/` (create), `POST /trainees/{id}` (update), `POST /klassen/{id}` (Mitglieder), `POST /schulplaene/{id}/wochen` (Woche hinzufügen), `DELETE /schulplaene/{id}/wochen/{wid}` (Woche entfernen), `DELETE /schulplaene/{id}` (Plan löschen).
- **Backfill**: `python -m seed.sync_school` materialisiert AUTO-Einträge für alle Trainees gegen die echte Datenbank.
- Neue Datei `app/services/school_sync.py` mit `sync_trainee`, `sync_class`, `resync_all`.

### Schulblöcke aus Klassenplan in allen Matrizen sichtbar

- Schulblöcke aus dem Klassen-Schulplan werden in allen Matrizen (Admin-Übersicht, Meine Einsätze, Meine Klasse) als BS- bzw. UNI-Block angezeigt, auch wenn kein expliziter Einsatz für die Woche vorhanden ist. Der abgeleitete Chip erscheint umrandet (`.cell-auto`: transparenter Hintergrund, 1 px Rahmen in der Typfarbe, leicht gedimmt) und ist so von einem echten Einsatz-Chip unterscheidbar. Ein expliziter Einsatz hat Vorrang und verdrängt den Plan-Chip.

### Klassen-Bearbeiten & UX-Bereinigung

- **Klassen-Mitglieder jetzt im Bearbeiten-Formular**: Die separate Detailseite (`GET /klassen/{id}`) und die `/mitglieder`-Route entfallen. Stattdessen enthält das Bearbeiten-Formular eine saubere vertikale Mitgliederliste (Checkboxen, scrollbar ab vielen Einträgen, Hinweis bei Azubis aus anderen Klassen). Klassen-Felder und Mitgliedschaft werden in einem einzigen `POST /klassen/{id}` gespeichert.
- **Zeilenklick → Bearbeiten**: Klick auf eine Klassenzeile öffnet direkt das Bearbeiten-Formular statt der nun entfernten Detailseite.
- **„built by RR × Claude"** – dezentes Gold-Credit in der unteren rechten Ecke der Über-Wilbeth-Seite.

### Bedienbarkeit & Azubi-Navigation

#### Admin
- **Klickbare Tabellenzeilen** in allen Stammdaten-Listen: Ein Klick auf die Zeile öffnet das Ziel (Trainees → Detailseite, Klassen → neue Klassen-Detailseite, übrige Listen → Bearbeiten). Globales `data-href`-Skript in `base.html`, das Klicks auf Buttons/Links/Formulare ignoriert (Löschen bleibt sicher).
- **Klassen-Detailseite** `GET /klassen/{id}`: Klassenname, Typ-Badge (inkl. Schultage bei TAGE_FEST) und eine **Mitglieder-Checkliste** aller Azubis (Haken = in dieser Klasse). `POST /klassen/{id}/mitglieder` setzt/entfernt `klasse_id` entsprechend; Trainees aus anderen Klassen werden mit Hinweis angezeigt. Alle dynamischen Klassen-Routen mit `:int`-Pfadkonverter abgesichert.
- **Seed**: `FISI 1. LJ` + `FIAE 1. LJ` als neue 1. Lehrjahre (BLOCK_FEST, leere Schulpläne, keine BS-Wochen/Trainees).

#### Azubi-Sicht
- **Linke Sidebar statt Tabs**: gemeinsames Layout `share/_base.html` mit „Meine Einsätze", „Meine Klasse", „Urlaub", „Wünsche", „Kalender (.ics)" und unten „Über Wilbeth" (Link auf die bestehende Seite).
- **„Meine Einsätze"** ist jetzt eine **Einzeilen-Matrix** (KW + Datum-Header, Heute-/Schulwochen-Markierung, Schultag-Hinweis) statt Band + Liste.
- **Urlaub** und **Wünsche** sind eigene Seiten (`/mein-plan/{token}/urlaub`, `/mein-plan/{token}/wuensche`).
- **Geteiltes read-only Matrix-Partial** `_partials/week_matrix.html` für „Meine Einsätze" und „Meine Klasse".

#### Tests
- `tests/test_klassen_detail.py` (Detailseite, Mitglieder-Zuweisung, 1.-LJ im Seed) + erweiterte `tests/test_share.py` (Sidebar-Links, Urlaub-/Wünsche-Seiten rendern). Gesamt-Suite **77 grün**.

### Sprint 6 – Multi-Beruf & Wochentag-Schule

#### Hinzugefügt
- **Neuer Unterrichts-Typ `TAGE_FEST`** (Bürokaufleute): gemischte Wochen mit festen Schultagen statt Blockwochen. Neue `TraineeClass`-Felder `schul_wochentage` (ISO-Wochentage, z. B. "2,3" = Di, Mi) und `halbtag_wochentag`. Migration `b3f2a9c5d1e7`.
- **BWL-Studenten** über `DH_PHASEN` (Blockphasen wie IT-DH) — kein neuer Mechanismus, nur Klasse + Studis.
- **Klassen-Formular**: Auswahl „Wochentag-Schule" + Wochentag-Picker (Mo–Fr) und Halbtags-Auswahl (per JS eingeblendet); Klassenliste zeigt Typ-Badge + Schultage.
- **Admin-Matrix**: Schultag-Badge an der Trainee-Zeile für `TAGE_FEST`-Klassen (z. B. „📚 Di, Mi").
- **Mein-Plan**: Hinweis „Deine festen Schultage" für Bürokaufleute.
- **Azubi-Sicht gesplittet** in zwei Tabs: „Meine Einsätze" (wie bisher) und **„Meine Klasse"** (`/mein-plan/{token}/klasse`) — read-only Matrix der eigenen Klasse, eigene Zeile hervorgehoben, mit Heute-/Schulwochen-Markierung, **ohne** Bearbeiten und **ohne** Konfliktanzeige. Jahres-Umschaltung bei mehreren Lehrjahren.
- Wochentag-Helfer `parse_weekdays` / `format_weekdays` in `app/utils/kw.py`.
- Seed: 7 neue Abteilungen (HR, Marketing, Facility, Vertrieb, Bank, Posteingang, Empfang), Klassen Büro 1./2./3. LJ (`TAGE_FEST`) + BWL (`DH_PHASEN`), 4 Bürokaufleute + 2 BWL-Studis mit Einsätzen. Jetzt 10 Klassen, 19 Abteilungen, 26 Trainees.
- Tests `tests/test_tage_fest.py` (10): Wochentag-Helfer, kein Schul-Konflikt für `TAGE_FEST`, Urlaub erlaubt, Modell-Roundtrip, Klassen-Formular, Matrix-Badge, Klassen-Matrix. Gesamt-Suite 71 grün.

#### Designentscheidung
- **Urlaub bei Wochentag-Schule** ist immer erlaubt: `TAGE_FEST`-Klassen haben keine `SchoolPlanWeek`-Einträge, daher greifen weder Schul-Konflikt noch Urlaubs-Sperre. Eine Wochen-`URLAUB` betrifft nur die Betriebstage; die festen Schultage bleiben als Overlay sichtbar. Keine Sonderlogik im Conflict-Checker nötig.

---

### Konflikt-Erklärung ("Warum?")
- **Konflikt-Panel in der Übersicht**: Neben „X Konflikte erkannt" gibt es jetzt einen Button „Warum? →", der per HTMX (`GET /overview/konflikte`) ein Panel mit allen Konflikten lädt — je Eintrag Art (Schul-/Ferien-/Doppelbelegung), KW, betroffene Person(en) und eine ausformulierte Begründung. Wird on demand geladen, ist also nach Zell-Änderungen immer aktuell.
- **Begründung im Zell-Dialog**: Klickt man in der Matrix auf eine Zelle, die an einem Konflikt beteiligt ist, zeigt der Inline-Dialog oben eine Warnbox mit Art + Erklärung (bei Doppelbelegung inkl. der anderen beteiligten Trainees).
- **`conflict_checker`**: `Conflict` um strukturierte Felder erweitert (`dept_id`, `holiday_name`, `trainee_ids`) und neue Funktion `describe_conflict()`, die daraus eine menschenlesbare Erklärung (title/badge/when/who/why) baut. Bestehende `message`/`kind`-Felder unverändert.
- **Doppelbelegung jetzt sichtbar**: Bisher wurden Doppelbelegungs-Zellen (trainee_id=None) in der Matrix nicht rot markiert. Jetzt werden alle beteiligten Trainees markiert (Matrix-Färbung + Live-Update nach Zell-Edit).
- Tests `tests/test_conflicts_ui.py` (9): `describe_conflict` je Konfliktart, Panel-Route (mit/ohne Konflikte), „Warum?"-Button, Zell-Dialog mit Schul- und Doppelbelegungs-Begründung. Gesamt-Suite 61 grün.

### Über-Wilbeth-Seite
- Neue Unterseite `/ueber-wilbeth` (Link „Über Wilbeth" unten links in der Sidebar): animierte Erzählseite zur Sage der Drei Bethen (Ambeth, Borbeth, Wilbeth) mit Sternenhimmel, Scroll-Reveal (IntersectionObserver) und Schlusszeile „…und Wilbeth spannt jetzt deinen Schicksalsfaden". Respektiert `prefers-reduced-motion`, funktioniert ohne JS (noscript-Fallback). Styles scoped im Template (`.myth-*`).
- Überarbeitung nach Review: einheitliche dunkle Seitenfarbe über den gesamten Inhaltsbereich (nur Sidebar bleibt), Deutung der Schwestern als Geburt/Leben/Tod inkl. Parallelen zu Nornen und Moiren, neue Metaphern-Sektion (roter Faden, den Faden verlieren, Text/Textur von lat. texere, Gewebe der Wochen). Schicksalsfaden jetzt vertikal über die ganze Seite, scroll-gesteuert gezeichnet (Pfad dynamisch per JS, Fortschritt an Scroll-Position gekoppelt), endet exakt auf dem Button „Dem Faden folgen", der bei Ankunft golden glüht.
- Neue Sektion „Und wer ist wer — heute?": Ambeth = der erste Tag, Borbeth = die Azubis/Studis (das Lernen und Reifen), Wilbeth = die App selbst (das Ordnen der Wochen). Pointe: „Borbeth gehört euer Lernen. Wilbeth gehört der Plan."
- Sage erweitert um die volkskundlichen Schichten: erweiterte Erzaehlung (Einsiedler-Schwestern, Ursula-Legende, nie heiliggesprochen), neue Sektion „Spuren in Stein und Namen" (Verehrungsorte Schildthurn/Leutstetten/Worms, Namensvarianten, Matronen-Deutung inkl. ehrlichem „umstritten"-Hinweis) und der Madln-Spruch („Katharina mit dem Radl") als Zitatblock.
- Schicksalsfaden überarbeitet: schlägt jetzt weit aus (Serpentine verläuft außerhalb der 680px-Textspalte, auf schmalen Screens reduzierte Deckkraft statt Kollision), endet an der Oberkante des Buttons „Dem Faden folgen"; bei Berührung pulsiert der Button golden (Keyframe-Glow, statisch bei `prefers-reduced-motion`).

---

### Sprint 5 – Phase 2 (Azubi-Self-Service)

#### Hinzugefuegt
- **Token-Zugang** `/mein-plan/{token}` (`app/routers/share.py`): jeder Trainee kann einen `share_token` (UUID4) bekommen. Capability-URL, strikt gescoped auf die eigenen Daten.
- **„Mein Plan"-Seite** (`templates/share/plan.html`, eigenes Layout ohne Admin-Sidebar): Wochen-Band pro Lehrjahr mit Schulwochen- und Heute-Markierung, keine Konflikt-Anzeige (interne Info).
- **Urlaub selbst eintragen** (Azubi): KW oder KW-Bereich, laeuft ueber die bestehende Eingabe-Hierarchie (`_resolve_range`) — kann BS/Schulwochen nicht ueberschreiben, Schulwochen werden uebersprungen. Eintraege erhalten `source=SELBST`. Loeschen nur fuer selbst eingetragene Urlaube.
- **Wunschliste**: Abteilungswuensche mit Prioritaet (1–3, neue Tabelle `trainee_wish`) + Freitext/Zeitwuensche (`trainee.wunsch_notiz`). Fuer die Planerin in der Trainee-Detailseite sichtbar.
- **ICS-Kalender-Export** `/mein-plan/{token}/calendar.ics`: All-Day-Block (Mo–Fr) pro KW, stabile UID je Assignment, abonnierbar in Outlook/Google.
- **Token-Verwaltung** in der Trainee-Detailseite: Link anzeigen/kopieren, neu erzeugen (rotiert, alter Link sofort ungueltig), deaktivieren.
- Neue `AssignmentSource`-Werte `SELBST` (Azubi-Eingabe) und `SAP` (reserviert fuer spaeteren SuccessFactors-Sync).
- Alembic-Migration `a7c1e9f4b2d8`: `trainee.share_token`, `trainee.wunsch_notiz`, Tabelle `trainee_wish`.
- Tests `tests/test_share.py` (12): Token-Zugriff, Urlaub-Eintrag/-Loeschung (gescoped), Schulwochen-Skip, Wuensche, ICS, Token-Rotation. Gesamt-Suite jetzt 50 Tests, alle gruen.

#### Geaendert
- `_apply_assignments` in `assignments.py` nimmt jetzt einen optionalen `source`-Parameter (Default `MANUAL`), damit der Self-Service `SELBST`-Urlaube schreiben kann.

#### Sicherheit
- Token = Capability-URL. Der Self-Service liest/schreibt ausschliesslich die Daten des per Token identifizierten Trainees (eigener Urlaub + eigene Wuensche), keine Admin-Routen, keine Fremddaten, keine Konfliktanzeige. Echte Auth (SAP/AD) loest den Token-Zugang spaeter ab.

---

### Sprint 5 – Phase 1 (Polish & UX)

#### Hinzugefuegt
- **Matrix: Datums-Header** — Spalten zeigen jetzt KW-Nummer + Datum des Wochen-Montags (zweizeilig).
- **Matrix: Heute-Marker** — die aktuelle ISO-KW wird in Header und Spalte gelb hervorgehoben; Legende ergaenzt. Auch in der Trainee-Detailseite (Zeile der aktuellen KW markiert).
- **Trainee-Liste: Suche** — Client-seitiges Filterfeld (Name, Klasse, Rolle), ohne Server-Roundtrip.
- **Print-Stylesheet** (`@media print`) — blendet Sidebar/Filter/Buttons aus, druckt die Matrix kompakt im Querformat, Chip-Farben bleiben erhalten.
- **Tests**: `test_overview_filters.py`, `test_trainee_detail.py`, `test_cell_endpoints.py` (route-level via TestClient). Gesamt-Suite jetzt 38 Tests, alle gruen.
- **README** komplett auf aktuellen Stand gebracht (Setup, Reset-Workflow, Tests, Architektur, Troubleshooting).

#### Behoben
- **Inline-Cell-Edit war kaputt** (echter Bug): `POST /einsaetze/{assignment_id}` war vor `POST /einsaetze/cell-save` registriert und fing `/cell-save` bzw. `/cell-delete` ab (`"cell-save"` → int-Konvertierung → 422). Dynamische ID-Routen in `assignments.py` und `trainees.py` tragen jetzt den `:int`-Pfad-Converter, sodass literale Pfade korrekt greifen.

#### Geaendert
- **Seed neu aufgesetzt**: 20 Personen statt Platzhalter — 13 Azubis mit alliterativen Namen (FISI 2./3. LJ, FIAE 2./3. LJ) + 7 DH-Studenten (DHBW WI/Cybersecurity). Realistische Einsaetze fuer 2025-2026 (Abteilungs-Rotationen + BS-Wochen als AUTO + Urlaub; DH-Studenten mit Praxis-/Theoriephasen). Abteilungen und Schulplaene unveraendert.

---

### Entfernt
- **`UnterrichtsTyp.ROTATIONS_BLOCK`** und der zugehoerige Plan-Generator (`app/services/plan_generator.py`, `tests/test_plan_generator.py`).
- Spalten `rotation_wochen_betrieb` und `rotation_wochen_schule` aus `trainee_class` (Alembic-Migration `f5db6557783c`).
- Generator-Button in `school_plans/detail.html`, Rotations-Felder im Klassen-Formular, Rotations-Badge in der Klassen-Liste.

### Begruendung
Auch die FIAEs an der Heinrich-Hertz-Schule Karlsruhe haben einen fixen Blockplan (kein wirklicher Rotations-Rhythmus). Die Schule veroeffentlicht den Plan jaehrlich und teilt das Lehrjahr in drei Sub-Bloecke (a, b, c) auf. Damit gibt es keine Klasse mehr, die einen automatischen Rotations-Generator braucht — alle BS-Wochen werden manuell aus dem offiziellen Blockplan eingetragen.

### Geaendert
- Seed: FIAE 2./3. LJ jetzt `BLOCK_FEST`, BS-Wochen aus HHS-Blockplan eingetragen (a-Block = FIAE 3. LJ, c-Block = FIAE 2. LJ).
- Seed: Lehrjahr 2026-2027 ergaenzt (Schuljahr, Ferien, Schulplaene fuer alle 6 Klassen, FIAE-Wochen aus `Blockplan_2627`).
  - Ferien 2026/27 sind BW-Schaetzwerte — bitte vor Produktiveinsatz mit offiziellem Kalender abgleichen.
- `PROJECT_BRIEF.md`: Generator-Erwaehnungen entfernt, Hinweis auf HHS-Sub-Bloecke aktualisiert (Klaerung abgeschlossen: eine Klasse pro LJ, alle grenke-FIAEs im gleichen Sub-Block).
- `README.md`: Service-Liste aktualisiert.

---

## [Sprint 3] - 2026-05-07

Einsatzplanung: Generator, Konfliktpruefung, Schulplaene-CRUD, Einsaetze-CRUD, Matrix-Ansicht.

### Hinzugefuegt
- **`app/utils/kw.py`** — ISO-8601-Kalenderwochen-Arithmetik:
  - `kw_to_monday(kw, year)` → `date`
  - `monday_to_kw(d)` → `(kw, year)`
  - `iter_schoolyear_weeks(...)` — Iterator ueber alle Wochen eines Lehrjahres
  - `holiday_contains_week(...)` — prueft ob eine KW in einem Ferienbereich liegt
- **`app/services/plan_generator.py`** — Implementierung `generate_school_plan()` _(in „Unreleased" wieder entfernt, siehe oben)_
- **`app/services/conflict_checker.py`** — Implementierung `find_conflicts()`:
  - `SCHUL_KONFLIKT`: ABTEILUNG oder URLAUB in einer Schulwoche laut SchoolPlan
  - `FERIEN_KONFLIKT`: BERUFSSCHULE oder UNI in einer Schulferienswoche
  - `DOPPELBELEGUNG`: mehrere Trainees in derselben Abteilung / KW (ausser `erlaubt_mehrfachbelegung`)
- **`tests/test_plan_generator.py`** (5 Tests, in „Unreleased" entfernt) + **`tests/test_conflict_checker.py`** (11 Tests, weiterhin gruen)
- **`app/routers/school_plans.py`** + Templates `school_plans/list.html`, `form.html`, `detail.html`:
  - Liste, Anlegen, Detailansicht mit Wochen-Tabelle
  - Woche manuell hinzufuegen (Upsert)
  - Einzelne Wochen per HTMX loeschen
  - „Automatisch generieren"-Button _(in „Unreleased" entfernt)_
  - Plan loeschen (kaskadiert Wochen manuell)
- **`app/routers/assignments.py`** + Templates `assignments/list.html`, `form.html`:
  - Einsaetze-Liste mit Filter nach Lehrjahr und Trainee
  - Anlegen, Bearbeiten, per HTMX loeschen
  - **Harte Sperre**: URLAUB in Schulwochen → sofortiger Fehler-Redirect (`?msg=error`)
- **`app/routers/overview.py`** + Template `overview/matrix.html`:
  - Matrix Trainee × KW: farbige Chips pro Einsatztyp
  - Schulwochen laut SchoolPlan werden hinterlegt hervorgehoben
  - Konflikte werden rot markiert, Zaehler im Seitenheader
  - Filter nach Lehrjahr und Klasse
  - Trainee-Name verlinkt auf gefilterte Einsaetze-Liste

### Geaendert
- `app/main.py` registriert drei neue Router: `overview`, `school_plans`, `assignments`
- `app/templates/base.html` — Sidebar erweitert um "Einsaetze" (Planung) und "Schulplaene" (Stammdaten)
- `app/static/style.css` — neue Klassen: `badge-yellow`, `.filter-bar`, `.btn-group`, `.detail-layout`, `.matrix-*`, `.cell-chip`, `.cell-ABTEILUNG` u. a.

### Designentscheidungen
- **Holiday pauses rotation, not resets**: Ferienwochen erhoehen den Rotations-Zaehler nicht. Das naechste Betrieb- oder Schul-Segment laeuft dort weiter, wo es vor den Ferien aufgehoert hat.
- **Conflict checker ist read-only**: Konflikte werden nur angezeigt, nie automatisch behoben. Einzige Ausnahme: URLAUB in Schulwoche wird im Router-Layer hart geblockt.
- **`source=AUTO` reserviert**: Plan-Generator beschreibt vorlaeuflg nur `SchoolPlanWeek`-Zeilen, keine `Assignment`-Zeilen. Die `AUTO`-Unterscheidung in `Assignment` bleibt fuer spaeteres "Plan auf Trainees spiegeln" erhalten.

---

## [Sprint 1] - 2026-05-07

Fundament: Datenmodell, Migrationen, Seed.

### Hinzugefuegt
- Projekt-Skelett mit `requirements.txt`, `.gitignore`, `.env.example`, `README.md`
- Python-venv + Dependencies (FastAPI 0.136, SQLModel 0.0.38, Alembic 1.18, pytest 9.0)
- `app/config.py` mit `pydantic-settings` (laedt `.env`)
- `app/database.py` mit Engine, Session-Factory, SQLite-FK-Pragma
- 8 SQLModel-Tabellen unter `app/models/`:
  - `schoolyear` (Lehrjahr mit String-PK z. B. "2025-2026")
  - `trainee_class` (Klasse, ohne Lehrjahr-Bindung — wiederkehrender Typ)
  - `school_holiday` (Schulferien pro Lehrjahr)
  - `school_plan` + `school_plan_week` (Schulplan + normalisierte Wochen)
  - `trainee` (FK auf Klasse `ON DELETE SET NULL`)
  - `department` (Code, Kategorie, Mehrfachbelegung-Flag)
  - `assignment` (mit `source` AUTO/MANUAL, UNIQUE auf `(trainee_id, kw, jahr)`)
- Alembic eingerichtet:
  - `alembic/env.py` zieht DB-URL aus `app.config.settings`, registriert `SQLModel.metadata`
  - `script.py.mako` ergaenzt um `import sqlmodel`, damit Auto-Generate-Migrations sauber laufen
  - Initiale Migration `cf3e27b74779_initial_schema.py` erzeugt und angewendet
- Service-Stubs unter `app/services/`:
  - `conflict_checker.py` — Interface fuer 3 Konflikt-Arten
  - `plan_generator.py` — Interface fuer ROTATIONS_BLOCK-Plan-Generator
- Seed-Skript `seed/seed.py` (idempotent):
  - 1 Lehrjahr (2025-2026)
  - 6 Schulferien (BW-Standardvorlage)
  - 6 Klassen (FISI 2./3. LJ, FIAE 2./3. LJ, DHBW WI, DHBW Cybersecurity)
  - 12 Abteilungen (BA mit `erlaubt_mehrfachbelegung = True`)
  - 13 Trainees (inkl. Praktikant + Umschueler ohne Klasse)
  - Schulplaene fuer FISI 2. und FISI 3. (manuelle BS-Wochen aus Brief)
  - 18 Beispiel-Einsaetze fuer Malvin Maier (KW 36/2025 - KW 1/2026)

### Designentscheidungen
- **Klasse als wiederkehrender Typ**: `trainee_class` hat keine `lehrjahr_id`. Beim Jahresuebergang wird `trainee.klasse_id` umgesetzt (z. B. von "FISI 2. LJ" auf "FISI 3. LJ").
- **Eine Assignment-Zeile pro KW**: UNIQUE-Constraint auf `(trainee_id, kw, jahr)`. Teilwochen sind nicht abbildbar — bewusste Vereinfachung wie in der bisherigen Excel.
- **`Assignment.source`**: bleibt drin (`AUTO`/`MANUAL`), damit spaeter klar ist, ob ein BS/UNI-Eintrag aus dem Klassenplan gespiegelt oder manuell ueberschrieben wurde.
- **Urlaub in BS-Wochen**: wird im Eingabe-Layer hart blockiert (kein Konflikt, sondern Validierungsfehler). Brueckentage bleiben als BS-Eintrag, Sonderabsprache laeuft ausserhalb des Systems.
- **Frontend ohne Build-Schritt**: Jinja2 + HTMX + Alpine.js statt React/Vue, damit das Tool ohne Node.js durch Nicht-Spezialisten gewartet werden kann.

### Verworfen / nicht umgesetzt
- Urlaubs-Konflikt als Warnung: durch UNIQUE-Constraint datenmodell-seitig unmoeglich, also nicht mehr noetig.
- `wochen` als JSON-Feld auf `school_plan`: stattdessen normalisierte Tabelle `school_plan_week` fuer saubere Queries und Indizes.
