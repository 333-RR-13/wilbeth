"""Test fuer die Über-Wilbeth-Seite (Sage der Drei Bethen)."""


def test_about_page(client, session):
    r = client.get("/ueber-wilbeth")
    assert r.status_code == 200
    assert "Drei Bethen" in r.text
    assert "Ambeth" in r.text
    assert "Borbeth" in r.text
    assert "Schicksalsfaden" in r.text
    # Geburt/Leben/Tod-Deutung + Metaphern-Sektion
    assert "Geburt" in r.text
    assert "Leben" in r.text
    assert "Tod" in r.text
    assert "rote Faden" in r.text
    # Vertikaler scroll-gesteuerter Faden vorhanden
    assert "myth-thread-path" in r.text
    # Anekdote: Azubis/Studis = Borbeth, die App = Wilbeth
    assert "Borbeth seid ihr" in r.text
    assert "Wilbeth ist diese App" in r.text
    # Erweiterte Sage: Verehrungsorte, Matronen, drei heilige Madln
    assert "Spuren in Stein und Namen" in r.text
    assert "Matronen" in r.text
    assert "Leutstetten" in r.text
    assert "drei heiligen Madl" in r.text
    assert "Katharina" in r.text


def test_sidebar_link_present(client, session):
    # Der Link sitzt im Sidebar-Footer jeder Seite
    r = client.get("/ueber-wilbeth")
    assert 'href="/ueber-wilbeth"' in r.text
    assert "Über Wilbeth" in r.text


def test_about_page_has_built_by_credit(client, session):
    """GET /ueber-wilbeth enthält das 'built by'-Credit."""
    r = client.get("/ueber-wilbeth")
    assert r.status_code == 200
    assert "built by" in r.text
