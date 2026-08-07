"""Tests fuer app/utils/text.py: linkify() (sichere Freitext->HTML-Darstellung
fuer Department.info_text) und is_safe_http_url() (Validierung von
Department.info_link).
"""
from markupsafe import Markup

from app.utils.text import is_safe_http_url, linkify


# ── linkify: Grundverhalten ──────────────────────────────────────────────────

def test_linkify_leer_ergibt_leeres_markup():
    assert linkify("") == Markup("")
    assert linkify(None) == Markup("")
    assert linkify("   ") == Markup("")


def test_linkify_gibt_markup_zurueck():
    assert isinstance(linkify("Hallo"), Markup)


def test_linkify_plain_text_wird_in_p_gewrappt():
    result = linkify("Hallo Welt")
    assert str(result) == "<p>Hallo Welt</p>"


def test_linkify_zeilenumbruch_wird_br():
    result = linkify("Zeile 1\nZeile 2")
    assert "<br>" in str(result)
    assert "Zeile 1" in str(result)
    assert "Zeile 2" in str(result)


def test_linkify_leerzeile_trennt_absaetze():
    result = linkify("Absatz 1\n\nAbsatz 2")
    text = str(result)
    assert text.count("<p>") == 2
    assert "Absatz 1" in text and "Absatz 2" in text


# ── linkify: URLs werden automatisch verlinkt ────────────────────────────────

def test_linkify_http_url_wird_link():
    result = str(linkify("Siehe http://example.com fuer mehr Infos"))
    assert '<a href="http://example.com"' in result
    assert 'rel="noopener noreferrer"' in result
    assert 'target="_blank"' in result


def test_linkify_https_url_wird_link():
    result = str(linkify("https://wilbeth.example.de/plan"))
    assert '<a href="https://wilbeth.example.de/plan"' in result


def test_linkify_trailing_punctuation_bleibt_ausserhalb_des_links():
    result = str(linkify("Siehe https://example.com."))
    assert '<a href="https://example.com"' in result
    # Der Punkt am Satzende gehoert NICHT mehr zur URL/zum Linktext
    assert "</a>." in result


# ── linkify: SICHERHEIT (Kernanforderung des Auftrags) ───────────────────────

def test_linkify_html_injection_wird_escaped_nicht_interpretiert():
    """<script>...</script> darf NIE als aktives Markup herauskommen."""
    result = str(linkify("<script>alert(1)</script>"))
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_linkify_javascript_url_wird_nicht_verlinkt():
    """javascript:-URLs duerfen NIE zu einem klickbaren Link werden."""
    result = str(linkify("javascript:alert(1)"))
    assert "<a " not in result
    assert "href" not in result


def test_linkify_data_url_wird_nicht_verlinkt():
    result = str(linkify("data:text/html,<script>alert(1)</script>"))
    assert "<a " not in result


def test_linkify_html_attribute_injection_via_url_bleibt_harmlos():
    """Ein Angreifer kann ueber den Text kein zusaetzliches Attribut/Tag
    einschleusen, auch nicht "getarnt" als URL-naher Text."""
    result = str(linkify('http://example.com" onmouseover="alert(1)'))
    assert "<script>" not in result
    # linkify setzt selbst genau 3 Attribute mit Anfuehrungszeichen
    # (href/rel/target = 6 rohe '"'). Der Nutzer-Text darf KEIN zusaetzliches
    # rohes '"' einschleusen -- seine Anfuehrungszeichen wurden escaped
    # (z. B. zu "&#34;"), sonst koennte er aus dem href-Attribut ausbrechen.
    assert result.count('"') == 6


# ── is_safe_http_url ──────────────────────────────────────────────────────────

def test_is_safe_http_url_akzeptiert_http():
    assert is_safe_http_url("http://example.com") is True


def test_is_safe_http_url_akzeptiert_https():
    assert is_safe_http_url("https://example.com/pfad?x=1") is True


def test_is_safe_http_url_lehnt_javascript_ab():
    assert is_safe_http_url("javascript:alert(1)") is False


def test_is_safe_http_url_lehnt_data_ab():
    assert is_safe_http_url("data:text/html,<script>alert(1)</script>") is False


def test_is_safe_http_url_lehnt_leer_ab():
    assert is_safe_http_url("") is False
    assert is_safe_http_url(None) is False


def test_is_safe_http_url_lehnt_ohne_host_ab():
    assert is_safe_http_url("http://") is False


def test_is_safe_http_url_lehnt_relative_pfade_ab():
    assert is_safe_http_url("/interne/seite") is False


def test_entities_bleiben_intakt_beim_satzzeichen_strippen():
    """Regression: ';' darf nicht als Satzzeichen vom Link-Ende gestrippt
    werden -- da erst escaped und dann verlinkt wird, endet ein Match haeufig
    auf einer HTML-Entity ("&#34;", "&amp;"), die dadurch kaputtginge."""
    out = str(linkify('https://x.de" dahinter'))
    assert "&#34;" in out or "&#34" not in out  # Entity vollstaendig oder gar nicht
    assert "&#34\"" not in out
    # Query-Parameter mit & bleiben als vollstaendige Entity erhalten
    out2 = str(linkify("https://x.de/a?b=1&c=2"))
    assert "&amp;c=2" in out2
    # Der Punkt am Satzende gehoert weiterhin NICHT zur URL
    out3 = str(linkify("Siehe https://x.de."))
    assert 'href="https://x.de"' in out3
    assert out3.rstrip("</p>").endswith(".")
