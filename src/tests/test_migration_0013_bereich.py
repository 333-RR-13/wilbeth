"""Unit-Test fuer die reine Klassifizierungslogik der Migration 0013
(TraineeClass.bereich / Department.zielgruppe).

Die eigentliche Migration wird NICHT hier, sondern manuell gegen eine
Offline-PG-DDL-Ausgabe und eine echte SQLite-Kopie geprueft (siehe
Projektauftrag "Migration real pruefen"). Hier wird nur die reine
Namens-Klassifizierungsfunktion importiert und getestet -- sie hat keine
Alembic-/DB-Abhaengigkeit.
"""
import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0013_bereich_zielgruppe.py"
)
_spec = importlib.util.spec_from_file_location("migration_0013_bereich", _MODULE_PATH)
_migration_0013 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration_0013)

_bereich_aus_klassenname = _migration_0013._bereich_aus_klassenname


def test_fisi_wird_it():
    assert _bereich_aus_klassenname("FISI 2. LJ") == "IT"


def test_fiae_wird_it():
    assert _bereich_aus_klassenname("FIAE 1. LJ") == "IT"


def test_fisi_lowercase_wird_it():
    """Gross-/Kleinschreibung spielt keine Rolle (Normalisierung via .upper())."""
    assert _bereich_aus_klassenname("fisi 3. LJ") == "IT"


def test_buerokaufleute_wird_kaufmaennisch():
    assert _bereich_aus_klassenname("Bürokaufleute 1. LJ") == "KAUFMAENNISCH"


def test_digital_business_management_wird_kaufmaennisch():
    assert _bereich_aus_klassenname("Digital Business Management") == "KAUFMAENNISCH"


def test_international_business_wird_kaufmaennisch():
    assert _bereich_aus_klassenname("International Business") == "KAUFMAENNISCH"


def test_leerer_name_wird_kaufmaennisch():
    assert _bereich_aus_klassenname(None) == "KAUFMAENNISCH"
    assert _bereich_aus_klassenname("") == "KAUFMAENNISCH"


def test_name_der_nur_mit_fisi_beginnt_zaehlt_auch():
    """Praefix-Match: "FISIologie" waere theoretisch IT -- bewusst einfache
    Praefix-Regel wie im Auftrag beschrieben (Namen, die MIT FISI/FIAE
    BEGINNEN)."""
    assert _bereich_aus_klassenname("FISI-Sonderklasse") == "IT"


def test_it_nahe_studiengaenge_werden_als_it_erkannt():
    """Eine reine FISI/FIAE-Praefixregel wuerde IT-Studiengaenge wie
    Wirtschaftsinformatik oder Cybersecurity faelschlich als kaufmaennisch
    einordnen -- technische Stichwoerter zaehlen deshalb ebenfalls als IT."""
    assert _bereich_aus_klassenname("DHBW Wirtschaftsinformatik") == "IT"
    assert _bereich_aus_klassenname("DHBW Cybersecurity") == "IT"
    assert _bereich_aus_klassenname("Angewandte Informatik") == "IT"
    assert _bereich_aus_klassenname("IT Systemelektroniker") == "IT"
    # Kaufmaennische Namen bleiben unberuehrt -- insbesondere darf kein
    # zufaelliges Teilwort ("DigITal", "SecurITy") greifen
    assert _bereich_aus_klassenname("Digital Business Management") == "KAUFMAENNISCH"
    assert _bereich_aus_klassenname("Bürokaufleute 2. LJ") == "KAUFMAENNISCH"
