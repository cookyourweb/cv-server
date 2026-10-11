"""CORS by route prefix for the browser routes of the panel (sign-up, profile, fit).

Only an exactly listed origin gets headers, and only on these routes. Machine routes
(keyed by X-Clave-Maquina) never get CORS.
"""
import pytest

import server as srv

PANEL = "https://panel.ejemplo"


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(srv, "ORIGENES_PERMITIDOS", [PANEL])
    with srv.app.test_client() as c:
        yield c


@pytest.mark.parametrize("ruta", [
    "/yo", "/health", "/perfil", "/consentimientos", "/consentimientos/almacenar_cv", "/cv", "/cv/es",
    "/extraccion", "/cuenta", "/encajes", "/ofertas/abc-123/encaje",
])
def test_panel_routes_answer_the_preflight_for_the_listed_origin(cliente, ruta):
    r = cliente.options(ruta, headers={"Origin": PANEL, "Access-Control-Request-Method": "PUT"})
    assert r.headers["Access-Control-Allow-Origin"] == PANEL
    assert r.headers["Access-Control-Allow-Methods"] == "GET, POST, PUT, DELETE, OPTIONS"
    assert r.headers["Access-Control-Allow-Headers"] == "Authorization, Content-Type"
    assert "Access-Control-Allow-Credentials" not in r.headers


@pytest.mark.parametrize("ruta", [
    "/usuarios", "/generar-cv", "/crear-oferta", "/registro", "/", "/perfiles", "/cvs", "/cuentas",
    "/ofertas", "/ofertas/abc", "/ofertas/abc/otra", "/ofertas/a/b/encaje", "/no-existe", "/encaje",
])
def test_other_routes_never_get_cors(cliente, ruta):
    for metodo in (cliente.get, cliente.options):
        r = metodo(ruta, headers={"Origin": PANEL})
        assert "Access-Control-Allow-Origin" not in r.headers


def test_an_unlisted_origin_gets_nothing_on_a_panel_route(cliente):
    r = cliente.options("/perfil", headers={"Origin": "https://otro.ejemplo"})
    assert "Access-Control-Allow-Origin" not in r.headers


def test_health_and_yo_keep_working_for_the_listed_origin(cliente):
    assert cliente.get("/health", headers={"Origin": PANEL}).headers["Access-Control-Allow-Origin"] == PANEL
    assert cliente.get("/yo", headers={"Origin": PANEL}).headers["Access-Control-Allow-Origin"] == PANEL
