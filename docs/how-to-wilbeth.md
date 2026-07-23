# How to Wilbeth 🎓

> Schritt-für-Schritt-Anleitung für alle Nutzergruppen.
> URL: `https://wilbeth.k8s-ai-apps-staging.grenke.com` — Anmeldung mit deinem normalen Firmen-Account (Microsoft-Login).

## 1. Anmelden — wer sieht was?

Einfach die URL öffnen → Microsoft-Login → Wilbeth erkennt deine Rolle automatisch:

| Rolle | Du landest auf | Du kannst |
|---|---|---|
| **Azubi** | deinem persönlichen Plan | eigenen Plan sehen, Urlaub eintragen, Wünsche abgeben, Kalender abonnieren |
| **Ausbilder** | „Meine Abteilung" | alles ansehen; Einsätze deiner Abteilung bestätigen, kommentieren, vorschlagen |
| **Orga** | der Übersicht | planen + Stammdaten pflegen |
| **Admin** | der Übersicht | alles, inkl. Jahresabschluss und Export/Import |

Siehst du **„Kein Zugriff"**: Bei Azubis fehlt meist der hinterlegte UPN (→ Orga Bescheid geben, die Seite zeigt deinen UPN an), bei Mitarbeitenden die Gruppen-Mitgliedschaft. Nach Gruppen-Änderungen einmal ab- und wieder anmelden.

---

## 2. Für Azubis

- **Mein Plan**: deine Einsätze Woche für Woche. Berufsschul-/Uni-Wochen kommen automatisch aus dem Klassen-Schulplan.
- **Meine Klasse**: die Pläne deiner Klassenkameraden.
- **Übersicht**: alle Azubis & Studis im Überblick (nur lesen).
- **Urlaub**: eigene Urlaubswochen eintragen/löschen.
- **Wünsche**: Abteilungen mit Priorität **Muss / Sollte / Kann** markieren + Freitext — Grundlage für den Auto-Plan.
- **Abteilungen**: Infos zu allen Abteilungen (Beschreibung, Ansprechpartner).
- **Kalender-Abo**: den ICS-Link deiner Seite in Outlook als Internetkalender abonnieren → Einsätze erscheinen automatisch im Kalender.

---

## 3. Für Ausbilder

### Meine Abteilung
Nach dem Login siehst du je verantworteter Abteilung die **anstehenden Einsätze als Blöcke** (z. B. „Jäger, Jonas — KW 38–41 — offen").

- **Bestätigen / Ablehnen** pro Block (ein Klick für alle Wochen des Blocks).
- **Anmerkung/Feedback** direkt am Block hinterlegen — z. B. nach dem Einsatz ein kurzes Feedback zum Azubi.
- Der Status erscheint als farbiger Punkt in der großen Übersicht (gelb = offen, grün = bestätigt, rot = abgelehnt).

### Einsatz vorschlagen
Unten auf „Meine Abteilung": Azubi + Zeitraum (KW von–bis) + Kommentar → **Vorschlag einreichen**. Orga prüft ihn; Status und Antwort siehst du in „Meine Vorschläge".

> Du siehst keine Abteilung? Dann fehlt dein UPN im Feld **„Verantwortliche Ausbilder"** deiner Abteilung — Orga/Admin trägt ihn unter *Abteilungen → Bearbeiten* ein.

---

## 4. Für Orga & Admin

### 4.1 Erst-Einrichtung (Reihenfolge beachten)
1. **Ausbildungsjahr** anlegen (z. B. 2025-2026, KW 36–35)
2. **Klassen** anlegen — Namenskonvention ist wichtig: **„FISI 1. LJ", „FISI 2. LJ", …** (daraus berechnet Wilbeth die Progression); DH-Kohorten frei benennen (z. B. „DHBW Cybersecurity")
3. **Abteilungen** (+ Kategorien, Verantwortliche-UPNs, Beschreibung)
4. **Schulpläne** je Klasse/Jahr (Blockwochen; Import per CSV/Einfügen) und **Schulferien**
5. **Trainees** anlegen (siehe 4.2)

### 4.2 Trainee anlegen — die zwei wichtigen Felder
- **Ausbildungsbeginn** (Pflicht): Regelfall **01.09.**; Ausnahme 01.01. des Folgejahres.
- **Ausbildungsberuf** (Pflicht): Wilbeth setzt die Einstiegsklasse automatisch auf „‹Beruf› 1. LJ".
- **Sonderfall-Häkchen** nur für echte Ausnahmen (z. B. Einstieg direkt im 2. LJ).

Aus diesen Angaben berechnet Wilbeth die Klasse für **jedes** Jahr automatisch — es gibt keinen manuellen Klassenwechsel. Merkregel: *Einstiegsklasse = Klasse beim Start, nie die heutige.*

Danach: **UPN-Pflege** (Button auf der Trainee-Liste) — UPNs aller Azubis in einer Tabelle pflegen; „Vorschläge generieren" füllt leere Felder aus den Namen vor. Ohne UPN kein SSO-Login für den Azubi (der persönliche Share-Link funktioniert als Fallback).

### 4.3 Einsätze planen (Übersicht)
- **Klick** = Zelle auswählen · **Doppelklick** = Einsatz öffnen/anlegen
- **Shift-Klick** = Bereich wählen · **Strg-Klick** = einzelne Zellen dazu
- **Ziehen** = Einsatz kopieren · **Strg+C / Strg+V** = Block kopieren
- Filter oben: Jahr, Klasse, Abteilung, **Halbjahr** (H1 = KW 36–10, H2 = KW 11–35), Wochen-Fenster (scrollbar)
- Rote Zellen = Konflikte; rechte Spalte zeigt, wo der Azubi schon war
- **Auto-Plan**: verteilt offene Wochen nach den Azubi-Wünschen (Muss/Sollte/Kann) — Vorschau, dann übernehmen
- **Import**: Excel-Matrix oder CSV (mit/ohne KW-Kopfzeile)

### 4.4 Vorschläge-Inbox
*Vorschläge* in der Navigation: eingereichte Ausbilder-Vorschläge **annehmen** (legt Einsätze in freien Wochen direkt als „bestätigt" an; belegte Wochen werden übersprungen und ausgewiesen) oder **ablehnen** (mit Kommentar).

### 4.5 Jahresabschluss (nur Admin, einmal pro Jahr)
*Jahresabschluss* → ältestes offenes Jahr ist vorausgewählt → pro Azubi Standard („rückt auf") oder Sonderfall wählen (**wiederholt / wechselt zu Klasse / Abbruch**) → **abschließen**. Das Jahr wird archiviert, Absolventen wandern automatisch ins Trainee-Archiv (reaktivierbar). ⚠️ Archivieren ist derzeit nicht per Klick umkehrbar — Jahr prüfen!

### 4.6 Export / Import (nur Admin)
Kompletten Datenbestand als **ZIP mit CSVs** exportieren → in Excel korrigieren → wieder importieren (**ersetzt alles**, mit Bestätigungs-Häkchen; bei Fehlern passiert gar nichts). Ideal für Massen-Korrekturen, z. B. Ausbildungsbeginn-Daten.

---

## 5. Häufige Fragen

**Ein Azubi steht im falschen Lehrjahr.** → Trainee-Liste: Tooltip auf der Klasse zeigt Einstieg + Beginn. Fast immer ist die Einstiegsklasse „zu hoch" (heutige statt Start-Klasse) — im Formular Beruf wählen, Sonderfall aus, speichern.

**Wie plane ich das nächste Ausbildungsjahr?** → Einfach das Jahr oben in der Übersicht wählen — alle rücken automatisch ein Lehrjahr vor.

**Ausbilder sieht seine Abteilung nicht.** → UPN ins Feld „Verantwortliche Ausbilder" der Abteilung + Mitgliedschaft in der Ausbilder-Gruppe.

**Azubi kann sich nicht anmelden.** → UPN in der UPN-Pflege prüfen (exakt wie auf der „Kein Zugriff"-Seite angezeigt).

**Wer darf was?** → Kurz: Ausbilder *bestätigen*, Orga *plant und pflegt*, Admin *darf zusätzlich abschließen und löschen*. Details in der Systemdokumentation.
