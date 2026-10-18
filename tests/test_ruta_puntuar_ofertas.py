"""POST /puntuar-ofertas: thin Flask route over puntuar_ofertas_core (ADR-001)."""
import pytest
import requests

import server as srv

CLAVE = "clave-de-prueba-larga-y-aleatoria"
CABECERAS = {"X-Clave-Maquina": CLAVE}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    with srv.app.test_client() as c:
        yield c


def test_the_route_returns_the_core_balance(cliente, monkeypatch):
    balance = {"ok": True, "puntuadas": 3, "saltadas": 1, "errores": 0, "sin_vectores": 2}
    monkeypatch.setattr(srv, "puntuar_ofertas_core", lambda: balance)
    r = cliente.post("/puntuar-ofertas", headers=CABECERAS)
    assert r.status_code == 200 and r.get_json() == balance


def test_the_route_needs_no_body(cliente, monkeypatch):
    monkeypatch.setattr(srv, "puntuar_ofertas_core", lambda: {"ok": True})
    assert cliente.post("/puntuar-ofertas", headers=CABECERAS, data="").status_code == 200


def test_when_notion_cannot_list_users_it_answers_502_without_the_error_text(cliente, monkeypatch):
    def cae():
        raise requests.RequestException("token secreto-123")
    monkeypatch.setattr(srv, "puntuar_ofertas_core", cae)
    r = cliente.post("/puntuar-ofertas", headers=CABECERAS)
    assert r.status_code == 502 and r.get_json()["ok"] is False
    assert "secreto" not in r.get_data(as_text=True)


def test_without_the_key_the_core_never_runs(cliente, monkeypatch):
    def prohibido():
        raise AssertionError("must not run without the machine key")
    monkeypatch.setattr(srv, "puntuar_ofertas_core", prohibido)
    assert cliente.post("/puntuar-ofertas").status_code == 401
