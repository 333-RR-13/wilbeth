# Wilbeth – Systemdokumentation

> Interne Web-Anwendung zur Einsatzplanung der IT-Auszubildenden bei grenke digital.
> Diese Seite beschreibt Architektur, Konzepte und Betrieb. Für die Bedienung siehe **„How to Wilbeth"**.

## 1. Überblick

Wilbeth ersetzt die Excel-basierte Einsatzplanung. Kernfunktionen:

- **Wochen-Matrix** (Übersicht): alle Azubis × Kalenderwochen eines Ausbildungsjahres, mit Konflikt-Erkennung, Filtern (Klasse, Abteilung, Halbjahr, Wochen-Fenster) und Drag-&-Drop-Planung.
- **Berechnetes Klassenmodell**: Klassen und Ausbildungsjahre werden aus dem Ausbildungsbeginn berechnet – kein manueller Jahreswechsel nötig.
- **Rollenbasierter Zugriff** über Entra ID (SSO): Admin, Orga, Ausbilder, Azubi.
- **Ausbilder-Selbstbedienung**: eigene Abteilungssicht, Einsätze bestätigen, Feedback, Einsatz-Vorschläge.
- **Azubi-Selbstbedienung**: eigener Plan, Klassen-Sicht, Urlaub, Wünsche, Kalender-Abo (ICS).

## 2. Technik-Stack

| Ebene | Technologie |
|---|---|
| Backend | Python 3.13, FastAPI, SQLModel (SQLAlchemy), Alembic-Migrationen |
| Frontend | Jinja2-Templates + HTMX (kein SPA-Framework) |
| Datenbank | PostgreSQL (Cluster), SQLite (lokale Entwicklung) |
| Auth | Entra ID via OIDC (Authlib), Session-Cookies |
| Deployment | Kubernetes (`ai-apps-staging01`), Kaniko-Build → Harbor, Azure-DevOps-Pipeline |
| Code-Fluss | GitHub (Arbeits-Spiegel) → lokal pullen → Push ins ADO-Repo → Pipeline baut & deployt |

**URL (DEV/Staging):** `https://wilbeth.k8s-ai-apps-staging.grenke.com`

## 3. Authentifizierung & Rollen

### 3.1 SSO (Entra ID, OIDC)

- Authorization Code Flow, Confidential Client. App-Registration **Wilbeth-DEV-OIDC**.
- Identität = **UPN** (`preferred_username`, Format `vNachname@grenkeleasing.com`).
- Rollen kommen aus dem **`groups`-Claim** (Objekt-IDs) des ID-Tokens.
- Kein SCIM: Nutzer werden Just-in-Time beim Login erkannt.
- Konfiguration ausschließlich über Umgebungsvariablen (`AUTH_MODE`, `OIDC_*`, `SESSION_SECRET`); Secrets nur als ADO-Pipeline-Variablen → k8s-Secret, nie im Repo.

### 3.2 Rollenauflösung (Reihenfolge)

1. Mitglied `SG-Wilbeth-DEV-Admin` → **Admin**
2. Mitglied `SG-Wilbeth-DEV-Orga` → **Orga**
3. Mitglied `SG-Wilbeth-DEV-Ausbilder` → **Ausbilder**
4. UPN passt auf einen aktiven Trainee-Datensatz → **Azubi** (Auto-Redirect auf den eigenen Plan)
5. sonst → „Kein Zugriff" (403-Seite zeigt zur Diagnose UPN + empfangene Gruppen + Claim-Liste)

Azubis benötigen **keine** Entra-Gruppe – nur den gepflegten UPN am Trainee (Seite „UPN-Pflege").
Gruppenänderungen wirken erst beim nächsten Login.

### 3.3 Rechte-Matrix

| Funktion | Ausbilder | Orga | Admin |
|---|---|---|---|
| Alles ansehen (Übersicht, Einsätze, Stammdaten) | ✓ | ✓ | ✓ |
| Einsätze bestätigen/ablehnen + Anmerkung + Feedback (nur eigene Abteilung) | ✓ | ✓ | ✓ |
| Einsatz-Vorschläge einreichen (eigene Abteilung) | ✓ | ✓ | ✓ |
| Einsätze planen (Zellen, Drag&Drop, Auto-Plan, Importe) | ✗ | ✓ | ✓ |
| Stammdaten pflegen (Trainees, UPN-Pflege, Klassen, Schulpläne, Ferien, Abteilungen) | ✗ | ✓ | ✓ |
| Vorschläge-Inbox (annehmen/ablehnen) | ✗ | ✓ | ✓ |
| Jahresabschluss | ✗ | ✗ | ✓ |
| Endgültiges Löschen (Archiv, Bulk-Delete, Stammdaten-Delete), Export/Import | ✗ | ✗ | ✓ |

„Eigene Abteilung" = der UPN des Ausbilders steht im Feld **„Verantwortliche Ausbilder"** der Abteilung.
Alle Rechte sind serverseitig erzwungen (403); die Navigation blendet zusätzlich aus.

### 3.4 Öffentliche Pfade (ohne Login)

`/auth/*` (Login-Flow), `/health` (k8s-Probes), `/static/*`, **`/mein-plan/{token}`** – die Azubi-Capability-Links.
Der Token *ist* dort die Authentifizierung; er wird auch vom ICS-Kalender-Abo (Outlook) genutzt, das kein OIDC kann.

## 4. Fachliche Kernkonzepte

### 4.1 Berechnetes Klassenmodell (der „Anker")

Jeder Trainee hat genau zwei Stammwerte für die Progression:

- **Ausbildungsbeginn** (Pflicht): Regelfall 01.09.; Ausnahme 01.01. des Folgejahres (zählt zum September-Jahrgang davor).
- **Einstiegsklasse** (wird beim Anlegen automatisch aus dem Pflichtfeld *Ausbildungsberuf* abgeleitet: „‹Beruf› 1. LJ" bzw. DH-Kohortenklasse; per **Sonderfall-Häkchen** direkt wählbar, z. B. Start im 2. LJ).

Die Klasse für ein beliebiges Ausbildungsjahr wird daraus **berechnet** (+1 Lehrjahr pro Jahr, Klassen-Namenskonvention „‹Beruf› ‹n›. LJ").
Wichtig: Die Einstiegsklasse ist die Klasse **beim Start**, nie die heutige – Liste/Übersicht/Jahresabschluss zeigen überall die *berechnete* aktuelle Klasse (der Anker steht als Tooltip in der Trainee-Liste).

- **DH-Studierende**: bleiben in ihrer Kohortenklasse; angezeigt wird ein berechnetes **Semester** (+1 pro Halbjahr).
- **Ausnahmen** (Wiederholen, Verkürzen, Wechsel): eine Klassen-Zuweisung für ein bestimmtes Jahr (Override) **re-verankert** die Progression ab diesem Jahr. Gesetzt wird sie im Jahresabschluss (Sonderfall-Editor) oder im Trainee-Formular (aufklappbarer Override-Block).
- **Zukunft ansehen**: einfach das künftige Ausbildungsjahr in der Übersicht wählen – hochgestufte Klassen erscheinen automatisch.

### 4.2 Jahresabschluss (statt Jahreswechsel)

Admin-Funktion. Schließt das **älteste offene** Ausbildungsjahr ab:

- Jahr wird **archiviert** (verschwindet aus den Auswahllisten; Daten bleiben erhalten).
- **Absolventen** (Azubis ohne Folgeklasse) werden automatisch ins Trainee-Archiv gesetzt (reaktivierbar).
- **Sonderfall-Editor**: pro Azubi wählbar – rückt auf (Standard) · wiederholt · wechselt zu Klasse · Abbruch.

### 4.3 Einsätze, Bestätigung, Vorschläge

- Einsatz = Zelle (Trainee × KW) mit Typ (Abteilung/BS/Uni/Urlaub/Frei), Quelle (manuell/auto/selbst) und – bei Abteilungseinsätzen – **Bestätigungsstatus** (offen/bestätigt/abgelehnt, farbiger Punkt in der Matrix), Anmerkung und **Feedback**.
- Schulwochen kommen automatisch aus den Klassen-Schulplänen; Auto-Plan verteilt offene Wochen nach Wunsch-Prioritäten (Muss/Sollte/Kann) und überschreibt nie Schulwochen.
- **„Meine Abteilung"** (Ausbilder): anstehende Einsätze als zusammenhängende Blöcke, Bestätigen/Ablehnen + Feedback pro Block; Formular „Einsatz vorschlagen".
- **Vorschläge-Inbox** (Orga/Admin): Annehmen legt Einsätze nur in freien Wochen an (direkt „bestätigt", übersprungene Wochen werden ausgewiesen); Ablehnen mit Kommentar.

### 4.4 Export / Import (Admin)

Seite **Export / Import**: kompletter Datenbestand als ZIP (eine CSV je Tabelle, inkl. IDs, Excel-tauglich).
Import = **atomares Ersetzen** mit Pflicht-Bestätigung: alles wird transaktional gelöscht und aus dem ZIP neu eingespielt (IDs/Beziehungen bleiben erhalten, Rollback bei jedem Fehler, Postgres-Sequenzen werden zurückgesetzt). Gedacht für Massen-Korrekturen in Excel.

## 5. Betrieb & Deployment

### 5.1 Deploy-Ablauf

1. Änderungen landen auf GitHub (`main`).
2. Lokal (WSL): `git pull` → `git push` ins **ADO-Repo** → Pipeline: Kaniko-Build → Harbor → `kubectl apply` (Kustomize-Overlay) → Rollout-Check.
3. Beim Container-Start führt der Entrypoint **`alembic upgrade head`** aus (setzt `replicaCount: 1` voraus).

### 5.2 Pipeline-Variablen (ADO, als *secret* markiert)

| Variable | Zweck |
|---|---|
| `dbPassword` | PostgreSQL-Passwort |
| `oidcClientSecret` | Client-Secret der Entra-App-Registration |
| `sessionSecret` | Signierschlüssel der Session-Cookies |

Fehlt eine → Pipeline bricht am `replacetokens`-Schritt ab.

### 5.3 Troubleshooting

| Symptom | Ursache/Prüfung |
|---|---|
| „Verify Wilbeth rollout" Timeout | Pod-Crash, meist Migration: `kubectl -n wilbeth logs deploy/wilbeth --previous`. Merke: Migrationen nur mit nullable Text-Spalten / `sa.false()` schreiben (SQLite ≠ Postgres!) |
| 403 „Kein Zugriff" trotz Gruppe | 403-Seite lesen: Gruppen leer → groups-Claim/Token-Konfiguration; falsche IDs → Gruppen-Mitgliedschaft; Gruppenänderung → neu einloggen |
| AADSTS50011 | Redirect-URI in der App-Registration stimmt nicht exakt |
| Falsche Klasse angezeigt | Anker prüfen (Tooltip in Trainee-Liste): Einstiegsklasse = Klasse **beim Start**? Beginn korrekt? |

### 5.4 Umgebungen

- **DEV/Staging**: aktueller Stand, Entra-App `Wilbeth-DEV-OIDC`, Gruppen `SG-Wilbeth-DEV-*` (Security-Typ).
- **Prod (geplant)**: eigene App-Registration + Redirect-URI, eigene Gruppen (⚠️ als **Security**-Typ anlegen – die vorhandenen `SG-Wilbeth-*` ohne DEV sind M365-Typ und landen ggf. nicht im groups-Claim), eigenes `dbPassword`/`sessionSecret`, Roadmap-Seite entfernen.

## 6. Offene Punkte

- Outlook-Kalender: Einsätze als .ics-Termin-Einladung per Mail (wartet auf Mailserver-Zugang); bis dahin ICS-Abo über den persönlichen Link.
- KI-gestützter Schulblockplan-Import (wartet auf API-Key, vor Prod).
- Automatischer Schulferien-Import aus dem Internet (CSV-Import existiert).
- Prod-Setup (siehe 5.4).
