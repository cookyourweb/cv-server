"""GET /yo shows the generation quota of a Neon user and omits it for exempt and legacy users.

Same setup as test_ruta_cuota: invited test personas against a real PostgreSQL, ledger rows told
apart by a test-only model id.
"""
from decimal import Decimal

import pytest
from sqlalchemy import text
from test_rutas_alta import _llamar, bd, cliente, migrado, par, personas  # noqa: F401

import base_de_datos
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
    assert _yo(cliente, ana)["cuota"] == {"usadas": 0.0, "limite": 8.0, "se_renueva": _primero_del_mes_siguiente(),
                                   "tope_agotado": False}
    _sembrar(ana, "2.3")
    assert _yo(cliente, ana)["cuota"]["usadas"] == 2.3


def test_yo_reports_the_global_cap_as_exhausted_when_not_even_a_letter_fits(cliente, ana, monkeypatch):
    letra = cuota.estimar_eur(0, max_tokens=cuota.MAX_TOKENS_CARTA)
    monkeypatch.setattr(cuota, "TOPE_EUR", letra - Decimal("0.0001"))
    assert _yo(cliente, ana)["cuota"]["tope_agotado"] is True


def test_yo_cap_is_not_exhausted_when_exactly_a_letter_still_fits(cliente, ana, monkeypatch):
    letra = cuota.estimar_eur(0, max_tokens=cuota.MAX_TOKENS_CARTA)
    monkeypatch.setattr(cuota, "TOPE_EUR", letra)
    assert _yo(cliente, ana)["cuota"]["tope_agotado"] is False


def test_yo_cap_counts_open_reservations_like_the_refusal_does(cliente, ana, monkeypatch):
    _sembrar(ana, "0.7", coste="1")
    with base_de_datos.transaccion() as c:  # an open reservation: no coste_real, the estimate counts
        c.execute(text(
            "INSERT INTO gastos_generacion (usuario_id, tipo, modelo, unidades, estado, coste_estimado) "
            "SELECT usuario_id, 'cv', :m, 0.7, 'reservada', 5 FROM usuario_emails WHERE email = :e"),
            {"m": MODELO, "e": ana.email})
    letra = cuota.estimar_eur(0, max_tokens=cuota.MAX_TOKENS_CARTA)
    monkeypatch.setattr(cuota, "TOPE_EUR", Decimal("6") + letra - Decimal("0.0001"))
    assert _yo(cliente, ana)["cuota"]["tope_agotado"] is True
    monkeypatch.setattr(cuota, "TOPE_EUR", Decimal("6") + letra)
    assert _yo(cliente, ana)["cuota"]["tope_agotado"] is False


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
