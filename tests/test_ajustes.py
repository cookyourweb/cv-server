"""PUT /ajustes/extraccion: the kill switch without a redeploy (machine key only).

Route inventory, CORS and the machine-key rule are also covered by test_rutas_de_maquina.py
(every route not listed as public must demand the key) and test_cors_prefijos.py.
"""
import pytest
from alembic import command
from sqlalchemy import text

import base_de_datos
import server as srv
from test_migracion_0001 import _alembic

CLAVE = "clave-de-prueba-larga-y-aleatoria"
CABECERAS = {"X-Clave-Maquina": CLAVE}


@pytest.fixture(scope="module")
def migrado(url_de_pruebas):
    _alembic(command.upgrade, "head", url_de_pruebas)


def _restaurar():
    with base_de_datos.transaccion() as c:
        c.execute(text("INSERT INTO ajustes (clave, valor) VALUES ('extraccion_activa', 'true'::jsonb) "
                       "ON CONFLICT (clave) DO UPDATE SET valor = 'true'::jsonb"))


@pytest.fixture
def cliente(monkeypatch, url_de_pruebas, migrado):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    monkeypatch.setenv("DATABASE_URL", url_de_pruebas)
    base_de_datos.cerrar()
    _restaurar()
    with srv.app.test_client() as c:
        yield c
    _restaurar()
    base_de_datos.cerrar()


def _valor():
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT valor FROM ajustes WHERE clave = 'extraccion_activa'")).scalar_one()


bd = pytest.mark.bd


def test_the_route_demands_the_machine_key():
    vista = srv.app.view_functions["alta.fijar_extraccion"]
    assert getattr(vista, "exige_clave_maquina", False) is True


@bd
@pytest.mark.parametrize("cabeceras", [{}, {"X-Clave-Maquina": "otra"}, {"Authorization": "Bearer x"}])
def test_without_the_right_key_it_is_a_401_and_changes_nothing(cliente, cabeceras):
    r = cliente.put("/ajustes/extraccion", json={"activa": False}, headers=cabeceras)
    assert r.status_code == 401 and _valor() is True


@bd
def test_S4_2_it_turns_the_switch_off_and_on(cliente):
    r = cliente.put("/ajustes/extraccion", json={"activa": False}, headers=CABECERAS)
    assert r.status_code == 200 and r.get_json() == {"activa": False} and _valor() is False
    r = cliente.put("/ajustes/extraccion", json={"activa": True}, headers=CABECERAS)
    assert r.status_code == 200 and r.get_json() == {"activa": True} and _valor() is True


@bd
@pytest.mark.parametrize("cuerpo", [{"activa": "false"}, {"activa": 0}, {"activa": None}, {}, {"activa": True, "x": 1}, [], None])
def test_an_invalid_body_is_a_422_and_changes_nothing(cliente, cuerpo):
    assert cliente.put("/ajustes/extraccion", json=cuerpo, headers=CABECERAS).status_code == 422
    assert _valor() is True


@bd
def test_a_database_failure_is_a_generic_503(cliente):
    def cae(*args, **kwargs):
        raise base_de_datos.ErrorDeBaseDeDatos("host secreto-db.internal")
    with pytest.MonkeyPatch.context() as mp:  # undone before the fixture restores the row
        mp.setattr(base_de_datos, "motor", cae)
        r = cliente.put("/ajustes/extraccion", json={"activa": False}, headers=CABECERAS)
    assert r.status_code == 503 and "secreto-db" not in r.get_data(as_text=True)


def test_without_a_database_it_is_a_503_not_a_500(monkeypatch):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    with srv.app.test_client() as c:
        r = c.put("/ajustes/extraccion", json={"activa": False}, headers=CABECERAS)
    assert r.status_code == 503 and r.get_json() == {"ok": False, "error": "servicio no disponible"}


def test_it_never_gets_cors(monkeypatch):
    monkeypatch.setattr(srv, "ORIGENES_PERMITIDOS", ["https://panel.ejemplo"])
    with srv.app.test_client() as c:
        r = c.options("/ajustes/extraccion", headers={"Origin": "https://panel.ejemplo"})
    assert "Access-Control-Allow-Origin" not in r.headers
