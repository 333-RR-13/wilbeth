"""Unit-Test fuer die reinen Klassifizierungsfunktionen der Migration 0016
(TraineeClass.art / department.erlaubte_berufe).

Die eigentliche Migration wird NICHT hier, sondern manuell gegen eine
Offline-PG-DDL-Ausgabe und eine echte SQLite-Kopie geprueft (siehe
Projektauftrag "Migration real pruefen"). Hier werden nur die reinen
Namens-Klassifizierungsfunktionen importiert und getestet -- sie haben keine
Alembic-/DB-Abhaengigkeit, analog test_migration_0013_bereich.py.
"""
import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0016_berufe.py"
)
_spec = importlib.util.spec_from_file_location("migration_0016_berufe", _MODULE_PATH)
_migration_0016 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration_0016)

_art_aus_klassenname = _migration_0016._art_aus_klassenname
_beruf_token_aus_klassenname = _migration_0016._beruf_token_aus_klassenname


# ── _art_aus_klassenname ──────────────────────────────────────────────────────

def test_fisi_2lj_wird_ausbildung():
    assert _art_aus_klassenname("FISI 2. LJ") == "AUSBILDUNG"


def test_buerokaufleute_1lj_wird_ausbildung():
    assert _art_aus_klassenname("Bürokaufleute 1. LJ") == "AUSBILDUNG"


def test_dhbw_digital_business_management_wird_studium():
    assert _art_aus_klassenname("DHBW Digital Business Management") == "STUDIUM"


def test_dh_kohorte_ohne_lj_muster_wird_studium():
    assert _art_aus_klassenname("DHBW Cybersecurity") == "STUDIUM"


def test_leerer_name_wird_ausbildung():
    """Fallback auf den Modell-Default 'AUSBILDUNG', falls kein Name vorliegt."""
    assert _art_aus_klassenname(None) == "AUSBILDUNG"
    assert _art_aus_klassenname("") == "AUSBILDUNG"


# ── _beruf_token_aus_klassenname ──────────────────────────────────────────────

def test_beruf_token_mit_lj_muster():
    assert _beruf_token_aus_klassenname("FISI 2. LJ") == "FISI"
    assert _beruf_token_aus_klassenname("Bürokaufleute 3. LJ") == "Bürokaufleute"


def test_beruf_token_ohne_lj_muster_ist_voller_name():
    assert _beruf_token_aus_klassenname("DHBW Digital Business Management") == "DHBW Digital Business Management"


def test_beruf_token_leerer_name():
    assert _beruf_token_aus_klassenname(None) == ""
    assert _beruf_token_aus_klassenname("") == ""
