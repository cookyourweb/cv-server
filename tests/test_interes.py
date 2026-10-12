"""POST /interes: the "tell me about packs / access through my academy" lead (ADR-010).

One row per user and kind, idempotent, no free text beyond `organizacion` (120 characters at
most). Real PostgreSQL, real signed tokens (throwaway key), everything cleaned afterwards.
"""
import pytest
from sqlalchemy import text
from test_rutas_alta import _llamar, _usuario_id, bd, cliente, migrado, par, personas  # noqa: F401

import base_de_datos

pytestmark = pytest.mark.bd


def _filas(persona):
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT tipo, organizacion FROM intereses WHERE usuario_id = :u ORDER BY tipo"),
                         {"u": _usuario_id(persona)}).all()


@pytest.fixture
def ana(cliente, personas):  # noqa: F811
    _llamar(cliente, "GET", "/yo", personas["ana"])
    return personas["ana"]


def test_without_a_token_it_is_a_401(cliente):
    assert cliente.post("/interes", json={"tipo": "paquetes"}).status_code == 401


def test_a_packs_interest_is_recorded_with_201(cliente, ana):
    r = _llamar(cliente, "POST", "/interes", ana, {"tipo": "paquetes"})
    assert r.status_code == 201 and r.get_json() == {"tipo": "paquetes", "organizacion": None}
    assert [tuple(f) for f in _filas(ana)] == [("paquetes", None)]


def test_an_academy_interest_keeps_the_organisation_trimmed(cliente, ana):
    r = _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia", "organizacion": "  Academia Sol  "})
    assert r.status_code == 201 and r.get_json() == {"tipo": "academia", "organizacion": "Academia Sol"}
    assert [tuple(f) for f in _filas(ana)] == [("academia", "Academia Sol")]


def test_posting_again_is_idempotent_one_row_per_kind(cliente, ana):
    for _ in range(3):
        assert _llamar(cliente, "POST", "/interes", ana, {"tipo": "paquetes"}).status_code == 201
    assert len(_filas(ana)) == 1


def test_a_second_post_updates_the_organisation_and_a_blank_one_keeps_the_previous(cliente, ana):
    _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia", "organizacion": "Primera"})
    _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia", "organizacion": "Segunda"})
    assert [tuple(f) for f in _filas(ana)] == [("academia", "Segunda")]
    r = _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia"})
    assert r.get_json()["organizacion"] == "Segunda"
    assert [tuple(f) for f in _filas(ana)] == [("academia", "Segunda")]


def test_each_kind_is_its_own_row(cliente, ana):
    _llamar(cliente, "POST", "/interes", ana, {"tipo": "paquetes"})
    _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia"})
    assert [f.tipo for f in _filas(ana)] == ["academia", "paquetes"]


def test_an_organisation_of_120_characters_fits_and_121_is_a_422(cliente, ana):
    assert _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia", "organizacion": "x" * 120}).status_code == 201
    r = _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia", "organizacion": "x" * 121})
    assert r.status_code == 422 and r.get_json()["campos"] == ["organizacion"]
    assert [f.organizacion for f in _filas(ana)] == ["x" * 120]


@pytest.mark.parametrize("cuerpo", [
    {}, {"tipo": "otro"}, {"tipo": 1}, {"tipo": "paquetes", "mensaje": "hola"}, {"tipo": "paquetes", "organizacion": 5},
    {"tipo": "paquetes", "organizacion": ["a"]}, None, [], "paquetes",
])
def test_an_invalid_body_is_a_422_and_stores_nothing_and_echoes_nothing(cliente, ana, cuerpo):
    r = _llamar(cliente, "POST", "/interes", ana, cuerpo)
    assert r.status_code == 422 and r.get_json()["ok"] is False
    assert _filas(ana) == []


def test_validation_errors_never_echo_the_submitted_values(cliente, ana):
    r = _llamar(cliente, "POST", "/interes", ana, {"tipo": "SECRETO-TIPO", "mensaje": "SECRETO-EXTRA"})
    assert r.status_code == 422 and "SECRETO" not in r.get_data(as_text=True)


def test_a_blank_organisation_is_stored_as_none(cliente, ana):
    r = _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia", "organizacion": "   "})
    assert r.status_code == 201 and r.get_json()["organizacion"] is None


def test_the_interest_is_always_the_callers_never_another_users(cliente, personas):
    for nombre in ("ana", "bea"):
        _llamar(cliente, "GET", "/yo", personas[nombre])
    _llamar(cliente, "POST", "/interes", personas["ana"], {"tipo": "paquetes"})
    assert len(_filas(personas["ana"])) == 1 and _filas(personas["bea"]) == []


def test_deleting_the_account_deletes_the_interests(cliente, ana):
    _llamar(cliente, "POST", "/interes", ana, {"tipo": "paquetes"})
    _llamar(cliente, "POST", "/interes", ana, {"tipo": "academia", "organizacion": "Academia"})
    uid = _usuario_id(ana)
    assert _llamar(cliente, "DELETE", "/cuenta", ana).status_code == 204
    with base_de_datos.transaccion() as c:
        assert c.execute(text("SELECT count(*) FROM intereses WHERE usuario_id = :u"), {"u": uid}).scalar_one() == 0
