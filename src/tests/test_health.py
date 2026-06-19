"""Test fuer den /health-Endpunkt (wird vom Docker HEALTHCHECK genutzt)."""


def test_health_returns_200_and_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
