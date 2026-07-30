"""Reine Daten-Definitionen der beiden Feedbackboegen (AUSBILDER/AZUBI).

Enthaelt ausschliesslich Konstanten (Skalen, Sektionen, Freitextfelder) und
eine kleine Hilfsfunktion zum Ermitteln aller Skala-Frage-Keys eines Typs.
Keine DB-Zugriffe, keine Seiteneffekte. UI-Labels sind hier bewusst MIT
echten Umlauten geschrieben (sie landen 1:1 in den Templates); Keys/Code
bleiben ASCII-only.
"""

VERSION_AUSBILDER = "DE-2019"
VERSION_AZUBI = "DE-2024"

# Einheitliche 5er-Skala (5 = beste Bewertung, 1 = schlechteste).
SKALA_ANFORDERUNGEN = [
    (5, "Anforderungen übertroffen"),
    (4, "Anforderungen teilweise übertroffen"),
    (3, "Anforderungen erfüllt (100%)"),
    (2, "Anforderungen teilweise nicht erfüllt"),
    (1, "Anforderungen nicht erfüllt"),
]

SKALA_ERWARTUNGEN = [
    (5, "Erwartungen übertroffen"),
    (4, "Erwartungen teilweise übertroffen"),
    (3, "Erwartungen erfüllt (100%)"),
    (2, "Erwartungen teilweise nicht erfüllt"),
    (1, "Erwartungen nicht erfüllt"),
]

EINSATZARTEN = ["Ersteinsatz", "Folgeeinsatz", "Projekteinsatz"]

STATUS_LABELS = {
    "entwurf": "Entwurf",
    "abgeschlossen": "Abgeschlossen",
    "besprochen": "Besprochen",
    "bestaetigt": "Vom Azubi bestätigt",
}

# Gemeinsame Status->Badge-Farbe fuer Staff- UND Azubi-UI (Farb-Suffix der
# .badge-*-Klassen in static/style.css). Eine einzige Quelle, damit derselbe
# Status in beiden Sichten dieselbe Farbe traegt.
STATUS_BADGE_FARBE = {
    "entwurf": "gray",
    "abgeschlossen": "orange",
    "besprochen": "blue",
    "bestaetigt": "green",
}

# ── Typ AUSBILDER (Fachausbilder ueber den Azubi) ────────────────────────────

AUSBILDER_SEKTIONEN = [
    {
        "titel": "Sozialkompetenz",
        "gruppen": [
            {
                "titel": "Kommunikation",
                "items": [
                    {"key": "komm_ausdruck", "text": "Drückt sich klar und deutlich aus"},
                    {"key": "komm_zuhoeren", "text": "Hört gut zu, stellt Rückfragen, zeigt Interesse"},
                ],
            },
            {
                "titel": "Teamverhalten",
                "items": [
                    {"key": "team_integration", "text": "Unterstützt und integriert sich aktiv im Team"},
                    {"key": "team_leistung", "text": "Fordert aktiv Aufgaben ein und ist leistungsbereit"},
                ],
            },
        ],
    },
    {
        "titel": "Methodenkompetenz",
        "gruppen": [
            {
                "titel": "Arbeitsorganisation",
                "items": [
                    {"key": "org_menge", "text": "Erledigt die geforderte Arbeitsmenge in angemessener Zeit"},
                    {"key": "org_prioritaeten", "text": "Setzt die richtigen Prioritäten, arbeitet eigenständig an übertragenen Aufgaben"},
                    {"key": "org_qualitaet", "text": "Arbeitet sorgfältig und zuverlässig, liefert Ergebnisse in guter Qualität"},
                ],
            },
        ],
    },
    {
        "titel": "Fachkompetenz",
        "gruppen": [
            {
                "titel": "Fachwissen",
                "items": [
                    {"key": "fach_grundverstaendnis", "text": "Grundverständnis der Abläufe in der Abteilung"},
                    {"key": "fach_zusammenhaenge", "text": "Verständnis über Gesamtzusammenhänge und Schnittstellen"},
                ],
            },
        ],
    },
    {
        "titel": "Persönliche Kompetenz",
        "gruppen": [
            {
                "titel": "Persönliches Auftreten",
                "items": [
                    {"key": "pers_engagement", "text": "Bringt sich mit Engagement und Motivation ein"},
                    {"key": "pers_umgang", "text": "Hat gute Umgangsformen"},
                ],
            },
        ],
    },
]

FREITEXT_AUSBILDER = [
    {"key": "zielvereinbarung", "label": "Zielvereinbarung (optional)", "mehrzeilig": True},
    {"key": "kommentar_lernziele", "label": "Kommentare zu den Lernzielen (bitte Einschätzungen begründen)", "mehrzeilig": True},
    {"key": "kommentar_kompetenzen", "label": "Kommentare zu den Kompetenzen (bitte Einschätzungen begründen)", "mehrzeilig": True},
    {"key": "staerken", "label": "Potentiale und Stärken (mind. 1 Punkt)", "mehrzeilig": True},
    {"key": "verbesserung", "label": "Verbesserungsmöglichkeiten (mind. 1 Punkt)", "mehrzeilig": True},
    {"key": "zielbeurteilung", "label": "Zielbeurteilung (optional)", "mehrzeilig": True},
]

# ── Typ AZUBI (Azubi ueber den Einsatz) ──────────────────────────────────────

AZUBI_SEKTIONEN = [
    {
        "titel": "Aufgaben",
        "items": [
            {"key": "aufg_kommunikation", "text": "Wurden die Arbeitsaufträge verständlich kommuniziert?"},
            {"key": "aufg_ausgewogen", "text": "Waren die Arbeitsaufträge ausgewogen und angemessen?"},
            {"key": "aufg_vorstellungen", "text": "Haben die Aufgaben deinen Vorstellungen entsprochen?"},
        ],
    },
    {
        "titel": "Unterstützung",
        "items": [
            {"key": "unt_fachausbilder", "text": "Hat die Unterstützung durch den Fachausbilder deinen Erwartungen entsprochen?"},
            {"key": "unt_team", "text": "Hat die Unterstützung durch das Team deinen Erwartungen entsprochen?"},
            {"key": "unt_integration", "text": "Fühlst du dich im Team willkommen, akzeptiert und integriert?"},
        ],
    },
]

FREITEXT_AZUBI = [
    {"key": "kommentar_lernziele", "label": "Kommentare zu den Lernzielen (bitte Einschätzungen begründen)", "mehrzeilig": True},
    {"key": "vermisste_themen", "label": "Gibt es Themenbereiche/Aufgaben, die du vermisst hast?", "mehrzeilig": True},
    {"key": "kommentar_beurteilung", "label": "Kommentare zur Beurteilung", "mehrzeilig": True},
    {"key": "highlight", "label": "Highlight (mind. 1 Punkt)", "mehrzeilig": True},
    {"key": "verbesserung", "label": "Verbesserungsmöglichkeiten (mind. 1 Punkt)", "mehrzeilig": True},
    {"key": "zielbeurteilung", "label": "Zielbeurteilung (optional)", "mehrzeilig": True},
]


def _keys_from_sektionen(sektionen: list[dict]) -> list[str]:
    """Sammelt alle Frage-Keys aus einer Sektionsliste (mit oder ohne
    Zwischenebene "gruppen")."""
    keys: list[str] = []
    for sektion in sektionen:
        if "gruppen" in sektion:
            for gruppe in sektion["gruppen"]:
                keys.extend(item["key"] for item in gruppe["items"])
        else:
            keys.extend(item["key"] for item in sektion["items"])
    return keys


def alle_frage_keys(typ: str) -> list[str]:
    """Gibt alle Skala-Frage-Keys des angegebenen Bogen-Typs zurueck.

    typ: "AUSBILDER" | "AZUBI". Unbekannter Typ -> leere Liste.
    """
    if typ == "AUSBILDER":
        return _keys_from_sektionen(AUSBILDER_SEKTIONEN)
    if typ == "AZUBI":
        return _keys_from_sektionen(AZUBI_SEKTIONEN)
    return []
