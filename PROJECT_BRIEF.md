# Wilbeth – Einsatzplanung für die IT-Ausbildung bei grenke digital

Hi Claude. Wir bauen zusammen eine interne Web-App namens **Wilbeth**, die die Einsatzplanung der IT-Auszubildenden bei der grenke digital GmbH digitalisiert. Aktuell läuft das in einer Excel-Datei, die fehleranfällig ist (Doppelbelegungen, übersehene Berufsschulwochen, vergessene Urlaube). Wilbeth soll das ersetzen.

Der Name kommt aus dem süddeutsch-alpenländischen Volksglauben – Wilbeth ist eine der Drei Bethen, Verkörperung der ordnenden, aktiv waltenden Kraft. Genau das, was die Software tut.

## Rolle und Arbeitsweise

- Du bist mein Pair-Programmer. Ich bin Auszubildender Fachinformatiker Systemintegration im 2. Lehrjahr und reviewe deinen Code.
- **Bevor** du Code schreibst: Schlage Architektur, Datenmodell und Tech-Stack vor und warte auf mein OK.
- Arbeite in kleinen Schritten. Nach jedem logischen Block: kurz zusammenfassen was gemacht wurde, vorschlagen was als nächstes kommt.
- Keine Halluzinationen: Wenn du eine Library oder API nicht sicher kennst, sag es und schlage vor sie nachzuschlagen.
- **Tests** für die Konflikt-Erkennung und den Schulplan-Generator sind Pflicht – das ist das Herzstück.
- Deutsche UI-Texte, englischer Code (Variablen, Funktionen, Kommentare).

## Technische Vorgaben

**Stack-Vorschlag** (gerne diskutieren bevor wir starten):
- Backend: Python + FastAPI, SQLite zum Start (später leicht auf PostgreSQL umstellbar)
- Frontend: einfache HTML/Jinja2-Templates oder leichtes React mit Vite – wartbar durch Nicht-Spezialisten
- Auth: erstmal keine, später Basic-Auth oder SSO als Erweiterungspunkt vorsehen
- Deployment-Ziel: Docker-Container, läuft im internen Netz auf einem Server

**Wichtig:** Wilbeth selbst nutzt **keine** externen KI-APIs. Du, Claude Code, bist nur das Entwicklungswerkzeug – das Endprodukt muss eigenständig im Firmennetz laufen, weil personenbezogene Daten der Auszubildenden verarbeitet werden.

## Domänenmodell

### Lehrjahr (Schoolyear)
Ein Lehrjahr läuft von KW 36 eines Jahres bis KW 35 des Folgejahres (Sept bis Aug). Der Plan ist pro Lehrjahr getrennt.
- `id` (string, z. B. "2025-2026")
- `start_kw`, `start_year`, `end_kw`, `end_year`

### Klasse (TraineeClass)
Eine Klasse = Lehrjahr + Ausbildungsrichtung. Definiert den Berufsschul-Rhythmus.
- `id`
- `name` (z. B. "FISI 2. LJ", "FISI 3. LJ", "FIAE 2. LJ", "DHBW Wirtschaftsinformatik", "DHBW Cybersecurity")
- `berufsschule` (string, z. B. "Josef-Durler Rastatt", "Heinrich-Hertz Karlsruhe", "DHBW Karlsruhe")
- `unterrichts_typ` (Enum):
  - `BLOCK_FEST` – Feste Block-Wochen pro Lehrjahr (FISI, FIAE). Plan kommt einmal pro Jahr von der Berufsschule, wird komplett manuell eingetragen, Ferien sind schon eingerechnet.
  - `DH_PHASEN` – Lange Uni-/Theorie-Blöcke (DHBW WI, DHBW Cybersecurity, **BWL**), werden manuell aus dem DHBW-Kalender eingetragen. Block-Logik wie `BLOCK_FEST`.
  - `TAGE_FEST` – **Wochentag-Schule** (Bürokaufleute): feste Schultage *jede Woche* statt Blockwochen. 1./2. LJ Di + Mi (Mi halbtags), 3. LJ Mo + Do. Zusätzliche Klassen-Felder `schul_wochentage` (z. B. "2,3" = Di, Mi; ISO Mo=1…So=7) und `halbtag_wochentag` (optional). Keine `SchoolPlanWeek`-Einträge — die Schultage ergeben sich aus diesen Feldern.

### Schulferien (SchoolHoliday)
Globale Liste pro Lehrjahr. Wird vom Schulplan-Generator berücksichtigt, sodass keine BS-Wochen in die Ferien gelegt werden. Standardvorlage: Schulferien Baden-Württemberg.
- `id`
- `lehrjahr_id` (FK)
- `name` (z. B. "Herbstferien", "Weihnachtsferien", "Osterferien", "Sommerferien")
- `start_kw`, `start_year`, `end_kw`, `end_year`

### Schulplan (SchoolPlan)
Liste der KWs pro Klasse + Lehrjahr, in denen die Klasse in BS oder Uni ist.
- `id`
- `klasse_id` (FK)
- `lehrjahr_id` (FK)
- `wochen` (Liste von `{kw, jahr, typ}` mit `typ` = BERUFSSCHULE oder UNI)

Schulpläne werden ausschließlich manuell gepflegt: Die jeweilige Berufsschule veröffentlicht den Blockplan zu Schuljahresbeginn, Azubi/Planerin trägt die BS-/Uni-Wochen einmal pro Lehrjahr ein.

### Trainee (Auszubildender)
- `id`
- `vorname`, `nachname`
- `klasse_id` (FK, optional – Praktikanten und Umschüler können ohne Klasse sein)
- `rolle` (Enum: AZUBI, DH_STUDENT, PRAKTIKANT, UMSCHUELER)
- `aktiv` (bool)
- `notizen` (text)

### Abteilung (Department)
- `id`
- `code` (kurz, z. B. "AI", "DP", "DWP")
- `name` (lang, z. B. "AI Platform")
- `kategorie` (Enum: ITO, NON_ITO, EXTERN)
- `ansprechpartner` (text)
- `erlaubt_mehrfachbelegung` (bool, default `false`, `true` für BA)

### Einsatz (Assignment)
Ein Eintrag = eine Person in einer Kalenderwoche.
- `id`
- `trainee_id` (FK)
- `lehrjahr_id` (FK)
- `kw` (int, 1–53)
- `jahr` (int, z. B. 2025 oder 2026)
- `typ` (Enum: ABTEILUNG, URLAUB, BERUFSSCHULE, UNI, FREI)
  - BERUFSSCHULE und UNI können entweder aus dem Klassen-Schulplan kommen (automatisch berechnet) oder individuell überschrieben werden
- `abteilung_id` (FK, nur wenn typ = ABTEILUNG)
- `notiz` (text, z. B. "Prüfung")

## Konflikt-Logik

Wilbeth blockiert **niemals hart**. Das System zeigt Warnungen, die Ausbildungsplanerin entscheidet bewusst.

**Konflikt-Arten:**
1. **Schul-Konflikt**: Person ist in Abteilung geplant, aber laut Klassen-Schulplan in BS oder Uni → Warnung
2. **Urlaubs-Konflikt**: Person ist in Abteilung geplant und gleichzeitig in Urlaub → Warnung
3. **Ferien-Konflikt**: BS-Eintrag fällt auf eine Schulferien-Woche → Warnung (kann z. B. passieren, wenn der Schulplan nicht aktualisiert wurde)
4. **Doppelbelegung Abteilung**: Mehrere Personen in derselben Abteilung in derselben KW
   - Wenn `abteilung.erlaubt_mehrfachbelegung == true` (z. B. BA) → **keine Warnung**
   - Sonst → Warnung mit Hinweis, welche Personen kollidieren

Konflikte werden bei jedem Speichern berechnet und in der Übersicht visuell markiert (z. B. gelbe Markierung der betroffenen Zelle, Tooltip mit Details).

## MVP-Funktionen

1. **CRUD** für Klassen, Trainees, Abteilungen, Lehrjahre, Schulferien
2. **Schulplan pro Klasse** anlegen und bearbeiten
   - Manuell: Liste der KWs direkt erfassen (gilt für alle Klassen)
3. **Einsätze** anlegen/bearbeiten/löschen pro Person
   - Anlegen wahlweise für **einzelne KW** oder **KW-Bereich** (z. B. KW 36–44, auch über Jahresgrenze)
   - Form zeigt das Abteilungs-Dropdown nur bei Typ = `ABTEILUNG`
   - **Eingabe-Hierarchie bei Doppelbelegung** (`BERUFSSCHULE = UNI` > `URLAUB` > `ABTEILUNG` > `FREI`):
     - Höhere Stufe überschreibt niedrigere automatisch (mit Info-Hinweis am Ende, *was* überschrieben wurde)
     - Niedrigere Stufe wird übersprungen (mit Info-Hinweis)
     - Gleiche Stufe → Bestätigungsseite listet alle Kollisionen auf, User wählt pro Eintrag „Überschreiben" oder „Verwerfen"
     - Hierarchie greift sowohl bei Range-Anlage als auch bei Single-KW-Anlage
4. **Konflikt-Erkennung** wie oben
5. **Kalender-/Matrix-Ansicht** wie in der Original-Excel:
   - Zeilen = Personen, Spalten = KWs des Lehrjahrs
   - Zellen zeigen Code (Abteilung, BS, U, Uni, Notiz)
   - Konflikte farblich markiert, Hover zeigt Details
   - **Inline-Edit**: Klick auf eine Zelle öffnet ein Mini-Form direkt in der Matrix (anlegen/bearbeiten/löschen ohne Seitenwechsel)
6. **Filter**: pro Lehrjahr, pro Klasse, pro Abteilung (Trainees ohne Einsatz in der Abt. werden ausgeblendet)
7. **Notizen** pro Einsatz (z. B. "Prüfung")
8. **Trainee-Detailseite**: Stammdaten + chronologische Einsatz-Historie + persönliche Konfliktliste + Schulplan der Klasse

## Sprint 5 (in Umsetzung)

**Phase 1 – Polish & UX (abgeschlossen):** Datums-Header + Heute-Marker in der Matrix, Trainee-Suche, Print-Stylesheet, Tests für Sprint-4-Features, aktualisiertes README.

**Phase 2 – Azubi-Self-Service (Token-Zugang, read + schmaler Schreibpfad):**
- Token-basierter Zugang: jeder Trainee bekommt einen `share_token` (UUID4), öffentliche URL `/mein-plan/{token}`
- „Mein Plan"-Seite: eigener Einsatzplan + Klassen-Schulplan, ohne Admin-Layout, **keine** Konflikt-Anzeige (interne Info)
- **Urlaub selbst eintragen:** Azubi kann eigene URLAUB-Wochen anlegen/entfernen. Läuft über die bestehende Eingabe-Hierarchie (kann BS/Schulwochen nicht überschreiben). Markiert mit `source=SELBST`. *(Falls später SAP-SuccessFactors-Anbindung möglich: Urlaub kommt automatisch mit `source=SAP`, manuelle Eingabe ist die Übergangslösung.)*
- **Wunschliste:** gewünschte Abteilungen mit Priorität (1–3, maschinenlesbar für den Planer) + Zeitwünsche/Freitext (`wunsch_notiz`, beratend für die Planerin)
- ICS-Kalender-Export (`/mein-plan/{token}/calendar.ics`), abonnierbar in Outlook/Google — All-Day-Block pro KW
- Token-Verwaltung in der Trainee-Detailseite (Link anzeigen/kopieren, neu erzeugen, deaktivieren); Anzeige der Wünsche für die Planerin

**Sicherheit:** Token = Capability-URL. Strikt gescoped: nur eigene Daten lesen, nur eigenen URLAUB + eigene Wünsche schreiben. Keine anderen Trainees, keine Admin-Routen. Echte Auth (SAP/AD) löst den Token-Zugang später ab.

## Roadmap nach Sprint 5

### Sprint 6 – Multi-Beruf & Wochentag-Schule
Die App soll langfristig **alle** Azubis/Studis abdecken, nicht nur IT-Blockunterricht.

**BWL-Studenten:** identisch zu den IT-DH-Studenten → `DH_PHASEN` (Blockphasen Uni/Betrieb). Kein neuer Mechanismus, nur neue Klasse + Studis im Seed.

**Bürokaufleute:** neuer Typ `TAGE_FEST` (gemischte Wochen, feste Schultage):
- 1./2. LJ Di + Mi (Mi halbtags), 3. LJ Mo + Do.
- **KW-Granularität bleibt** — ein Azubi ist pro Woche in *einer* Abteilung; die Schultage sind eine Eigenschaft der Klasse (siehe `TAGE_FEST` oben), keine `SchoolPlanWeek`-Einträge.
- **Urlaub** ist immer erlaubt: Eine Wochen-`URLAUB` betrifft nur die Betriebstage; die festen Schultage bleiben bestehen (werden weiterhin als Overlay angezeigt). Es gibt für `TAGE_FEST` keine „Schulwochen", also auch keine Urlaubs-Sperre und keinen Schul-Konflikt — fällt automatisch aus dem Fehlen von `SchoolPlanWeek`.
- **Anzeige:** Trainees einer `TAGE_FEST`-Klasse zeigen ihre Schultage als Hinweis (Matrix-Zeile + Zell-Overlay, Tooltip „Schultage: Di, Mi"), unterdrückt in Ferienwochen.

**Abteilungen (Bürokaufleute):** HR, Marketing, Facility, Vertrieb, CISO (bestehend, geteilt mit IT), Bank, Posteingang, Empfang. Kategorie `NON_ITO`.

**Filter:** der bestehende Klassen-Filter reicht — keine zusätzliche Beruf-Gruppierung nötig.

**Azubi-Sicht erweitern (Self-Service):** Die Mein-Plan-Seite wird in zwei Ansichten gesplittet:
- „Meine Einsätze" — wie bisher (eigenes Wochen-Band, Urlaub eintragen, Wünsche).
- „Meine Klasse" — read-only Matrix der eigenen Klasse (Zeilen = Klassenkamerad:innen, Spalten = KWs), eigene Zeile hervorgehoben. Mit Heute-/Schulwochen-Markierung und Schultag-Overlay (TAGE_FEST), aber **ohne** Inline-Edit und **ohne** Konfliktanzeige (interne Info). Datenschutz: nur die eigene Klasse sichtbar.

### Sprint 7 – Auto-Planer
- Button „Einsatz vorschlagen" pro **einzelnem Trainee**: füllt nur **leere** Wochen, erzeugt einen **reviewbaren** Vorschlag (`source=AUTO`), manuelle Einträge bleiben unangetastet.
- Berücksichtigt: Schulwochen/Schultage, Ferien, Doppelbelegung, Rotation (mehrere Abteilungen über die Ausbildung), **Wünsche** (Abteilungs-Prioritäten aus Sprint 5 P2).
- Heuristik/greedy zuerst (kein ILP-Solver); Vorschlag → Bestätigen über den bestehenden Confirm-Flow.

## Zusätzlich umgesetzt (über die Roadmap hinaus, siehe CHANGELOG)

- **Konflikt-Erklärung** („Warum?"-Panel + Begründung im Zell-Dialog).
- **Schulblöcke sichtbar + automatische Schul-Einsätze**: Schulplan-Wochen werden für alle Klassenmitglieder als `BERUFSSCHULE`/`UNI`-Einsätze (`source=AUTO`) materialisiert und synchron gehalten (nur leere Wochen, manuelle Einträge bleiben).
- **Abteilungs-Historie**: „War-schon-in"-Anzeige in der Planungszeile + weiche Wiederholungs-Warnung beim Zuweisen (kein Block).
- **Bedienbarkeit**: klickbare Tabellenzeilen, Klassen-Mitglieder im Bearbeiten-Tab, Azubi-Sidebar.
- **Deployment vorbereitet**: Dockerfile + Kubernetes-Manifeste (inkl. PostgreSQL-StatefulSet) + Azure-DevOps-Pipelines (Build → Harbor → Deploy auf `tools-test`/`prod`). Platzhalter müssen mit den Firmen-Werten gefüllt werden.

## Backlog (später)

- **Auto-Planer (Sprint 7)** — Vorschlags-Button mit Wünschen (noch offen).
- **PostgreSQL für Prod**: Alembic-Migrationen einmal gegen echtes Postgres verifizieren (Enum-Migration `f5db…` ist das Risiko).
- SAP-SuccessFactors-Anbindung (Urlaub automatisch) — abhängig von Compliance/Credentials
- Excel-Import/Export
- E-Mail-Benachrichtigungen
- **User-Auth mit echtem Login** — Anbindung an bestehendes System (SAP, Active Directory); User sind dort bereits angelegt. Bis dahin dient der Token-Zugang (Sprint 5 P2) als Übergangslösung. **Blocker für Produktivbetrieb** (App ist bis dahin offen → nur netzintern).

## Beispieldaten zum Seed (anonymisiert, aus realer Excel)

### Lehrjahr
- ID: "2025-2026", Start: KW 36/2025, Ende: KW 35/2026

### Schulferien Baden-Württemberg 2025-2026 (zum Befüllen)

| Name | Zeitraum (KW) |
|---|---|
| Herbstferien | KW 44/2025 |
| Weihnachtsferien | KW 52/2025 – KW 1/2026 |
| Faschingsferien (bewegliche Ferientage) | KW 8/2026 |
| Osterferien | KW 14–15/2026 |
| Pfingstferien (bewegliche Ferientage) | KW 21/2026 |
| Sommerferien | KW 31–35/2026 |

(Konkrete Wochen bitte beim Setup mit aktuellem Schulferienkalender abgleichen.)

### Klassen für Lehrjahr 2025-2026

| Klasse | Berufsschule | Unterrichts-Typ | Rotation-Config |
|---|---|---|---|
| FISI 2. LJ | Josef-Durler Rastatt | BLOCK_FEST | – |
| FISI 3. LJ | Josef-Durler Rastatt | BLOCK_FEST | – |
| FIAE 2. LJ | Heinrich-Hertz Karlsruhe | BLOCK_FEST | – |
| FIAE 3. LJ | Heinrich-Hertz Karlsruhe | BLOCK_FEST | – |
| DHBW Wirtschaftsinformatik | DHBW Karlsruhe | DH_PHASEN | – |
| DHBW Cybersecurity | DHBW Karlsruhe | DH_PHASEN | – |

> **HHS Karlsruhe (FIAE) — Blockstruktur geklärt:** Der HHS-Blockplan teilt jedes FIAE-Lehrjahr in drei Sub-Blöcke (a, b, c) auf. Grenke schickt ausschließlich Anwendungsentwickler (FA), für die gilt: **a-Block = FIAE 3. LJ**, b-Block = FIAE 1. LJ (aktuell keine grenke-Azubis), **c-Block = FIAE 2. LJ**. Da alle grenke-FIAEs eines Lehrjahrs im gleichen Sub-Block sitzen, reicht eine Klasse pro Lehrjahr — kein Splitting nötig. BS-Wochen sind aus `Blockplan_2526` und `Blockplan_2627` im Seed hinterlegt.

### Schulpläne 2025-2026 (manuelle Einträge)

| Klasse | BS-/Uni-Wochen |
|---|---|
| FISI 2. LJ | KW 38, 39, 45, 3, 4, 9, 10, 17, 18 (BS) |
| FISI 3. LJ | KW 40, 41, 47, 48, 49, 4, 5, 13, 14 (BS) |
| DHBW WI | wird manuell gepflegt (z. B. KW 6–18 Uni-Block) |
| DHBW Cybersecurity | wird manuell gepflegt |

Die FIAE-Pläne werden **vom Generator vorgeschlagen** auf Basis Rotations-Config + Schulferien.

### Abteilungen

| Code | Name | Kategorie | Mehrfachbelegung |
|---|---|---|---|
| AI | AI Platform | ITO | nein |
| DP | Delivery Platform | ITO | nein |
| DWP | Digital Workplace Platform | ITO | nein |
| OP | Observability Platform | ITO | nein |
| CP | Cloud Platform | ITO | nein |
| Sec | Security | ITO | nein |
| IAM | IAM Platform | ITO | nein |
| CISO | CISO | ITO | nein |
| BA | Business Applications | NON_ITO | **ja** |
| CS | Customer Service | NON_ITO | nein |
| DDAS | Data Driven Application | NON_ITO | nein |
| KGaA | KGaA | NON_ITO | nein |

### Beispiel-Trainees (für Seed)

| Vorname | Nachname | Klasse | Rolle |
|---|---|---|---|
| Max | Mustermann | FISI 2. LJ | AZUBI |
| Marvin | Meier | FISI 2. LJ | AZUBI |
| Malvin | Maier | FISI 2. LJ | AZUBI |
| Maximilian | Müller | FISI 2. LJ | AZUBI |
| Bob | Bauer | FISI 3. LJ | AZUBI |
| Beau | Beier | FISI 3. LJ | AZUBI |
| Paul | Pasch | FIAE 2. LJ (vorläufig) | AZUBI |
| Rado | Rusla | FIAE 2. LJ | AZUBI |
| Arafat | Araba | DHBW WI | DH_STUDENT |
| Horst | Huber | DHBW Cybersecurity | DH_STUDENT |
| Sebastian | Seele | DHBW Cybersecurity | DH_STUDENT |
| Kai-Uwe | Kreuz | (keine) | UMSCHUELER |
| Patrick | Prakti | (keine) | PRAKTIKANT |

### Beispiel-Einsätze für „Maier, Malvin" (FISI 2. LJ, ID = mein Beispiel)

| KW | Jahr | Typ | Abteilung | Notiz |
|---|---|---|---|---|
| 36 | 2025 | ABTEILUNG | CS | |
| 37 | 2025 | ABTEILUNG | CS | |
| 38 | 2025 | BERUFSSCHULE | – | (aus Klassenplan) |
| 39 | 2025 | BERUFSSCHULE | – | (aus Klassenplan) |
| 40 | 2025 | ABTEILUNG | CP | |
| 41 | 2025 | ABTEILUNG | CP | |
| 42 | 2025 | ABTEILUNG | BA | |
| 43 | 2025 | ABTEILUNG | BA | |
| 44 | 2025 | ABTEILUNG | CP | |
| 45 | 2025 | BERUFSSCHULE | – | (aus Klassenplan) |
| 46–50 | 2025 | ABTEILUNG | CP | |
| 51, 52 | 2025 | URLAUB | – | |
| 1 | 2026 | URLAUB | – | |

## Erste Aufgabe

Lies dir alles durch. Dann:

1. **Stelle 3–5 Rückfragen**, falls etwas unklar oder widersprüchlich ist.
2. **Schlage einen Tech-Stack final vor**, mit kurzer Begründung pro Wahl.
3. **Schlage eine Projektstruktur** vor (Ordner/Dateien).
4. **Bestätige das Datenmodell** oder schlage Verbesserungen vor (Indizes, Constraints, Edge Cases).
5. **Schlage einen ersten Sprint vor**: konkret, was bauen wir in den ersten 1–2 Sessions. Vorschlag von mir: Datenmodell + Migrations + CRUD für Stammdaten (Klassen, Abteilungen, Trainees, Schulferien) zuerst – vor der Konflikt-Logik und der Matrix-Ansicht.

Erst nach meinem OK auf diese Punkte fängst du mit Code an.

## Offene Punkte (von mir später zu klären)

- **DHBW Uni-Phasen**: Vollständiger Jahres-Rhythmus muss noch dokumentiert werden – fehlende Daten in der Beispiel-Excel
- **Datenschutzkonzept**: Wird vor Produktiv-Pilot mit DSB der grenke digital abgestimmt
- **Compliance Claude-Code-Nutzung**: Mit IT-Compliance abklären, ob Source-Code-Sharing mit Anthropic während Entwicklung OK ist
- **Schulferien-Daten 2025-2026**: Konkrete KWs aus offiziellem Schulferienkalender BW abgleichen