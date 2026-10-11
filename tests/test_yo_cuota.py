"""GET /yo shows the generation quota of a Neon user and omits it for exempt and legacy users.

Same setup as test_ruta_cuota: invited test personas against a real PostgreSQL, ledger rows told
apart by a test-only model id.
"""
import pytest
from test_rutas_alta import _llamar, bd, cliente, migrado, par, personas  # noqa: F401

import cuota
from test_ruta_cuota import MODELO, _primero_del_mes_siguiente, _sembrar, _yo, _limpiar

pytestmark = pytest.mark.bd


@pytest.fixture(autouse=True)
def entorno(monkeypatch, bd):  # noqa: F811
    monkeypatch.delenv("CUOTA_EXENTAS", raising=False)
    _limpiar()
    yield
    _limpiar()


@pytest.fixture
def ana(cliente, personas):  # noqa: F811
    _llamar(cliente, "GET", "/yo", personas["ana"])
    return personas["ana"]


def test_yo_shows_the_quota_of_a_neon_user_with_one_decimal(cliente, ana):
    assert _yo(cliente, ana)["cuota"] == {"usadas": 0.0, "limite": 8.0, "se_renueva": _primero_del_mes_siguiente()}
    _sembrar(ana, "2.3")
    assert _yo(cliente, ana)["cuota"]["usadas"] == 2.3


def test_yo_keeps_working_and_omits_the_quota_when_the_ledger_is_unavailable(cliente, ana, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def cae(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("secreto-db"))
    monkeypatch.setattr(cuota, "estado_de", cae)
    cuerpo = _yo(cliente, ana)
    assert cuerpo["email"] == ana.email and "cuota" not in cuerpo


def test_yo_omits_the_quota_for_an_exempt_user(cliente, ana, monkeypatch):
    monkeypatch.setenv("CUOTA_EXENTAS", ana.email)
    assert "cuota" not in _yo(cliente, ana)
