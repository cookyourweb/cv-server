"""Migration 0002_cuota: generation ledger, monthly alarm marker and interest leads.

Same style as test_migracion_0001: schema tests run in a rolled-back transaction; the round trip
(one revision down and up) is destructive and gated by ALLOW_DESTRUCTIVE_DB_TESTS.
"""
import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

import base_de_datos
from test_migracion_0001 import _alembic, _rechaza, _usuario, c, motor  # noqa: F401

pytestmark = pytest.mark.bd

TABLAS = {"gastos_generacion", "avisos_gasto", "intereses"}


@pytest.mark.bd_destructiva
def test_downgrade_to_0001_and_back_is_clean(motor, url_de_pruebas):  # noqa: F811
    try:
        _alembic(command.downgrade, "0001_alta", url_de_pruebas)
        nombres = set(inspect(motor).get_table_names())
        assert TABLAS.isdisjoint(nombres) and "extracciones" in nombres
        _alembic(command.upgrade, "head", url_de_pruebas)
        assert TABLAS <= set(inspect(motor).get_table_names())
    finally:
        _alembic(command.upgrade, "head", url_de_pruebas)


def _gasto(tipo="cv", unidades="0.7", estado="reservada", uid=None, estimado="0.1"):
    return ("INSERT INTO gastos_generacion (usuario_id, tipo, modelo, unidades, estado, coste_estimado) "
            "VALUES (:u, :t, 'm', :n, :e, :est)", {"u": uid, "t": tipo, "n": unidades, "e": estado, "est": estimado})


def test_a_ledger_row_gets_id_and_timestamp_and_accepts_the_valid_states(c):  # noqa: F811
    uid = _usuario(c)
    for estado in ("reservada", "completada", "fallida"):
        c.execute(text(_gasto(estado=estado, uid=uid)[0]), _gasto(estado=estado, uid=uid)[1])
    fila = c.execute(text("SELECT id, creado_en, coste_real FROM gastos_generacion LIMIT 1")).one()
    assert fila.id is not None and fila.creado_en is not None and fila.coste_real is None


@pytest.mark.parametrize("cambios", [{"tipo": "poema"}, {"estado": "rara"}, {"unidades": "-0.1"}, {"estimado": "-1"}])
def test_the_ledger_rejects_unknown_types_states_and_negative_amounts(c, cambios):  # noqa: F811
    sql, params = _gasto(**cambios)
    _rechaza(c, sql, **params)


def test_deleting_the_user_keeps_the_spend_anonymous_so_the_cap_cannot_be_reset(c):  # noqa: F811
    uid = _usuario(c)
    c.execute(text(_gasto(uid=uid, estimado="3.5")[0]), _gasto(uid=uid, estimado="3.5")[1])
    c.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": uid})
    fila = c.execute(text("SELECT usuario_id, coste_estimado FROM gastos_generacion "
                          "WHERE coste_estimado = 3.5 ORDER BY creado_en DESC LIMIT 1")).one()
    assert fila.usuario_id is None


def test_the_alarm_marker_is_one_row_per_month(c):  # noqa: F811
    c.execute(text("INSERT INTO avisos_gasto (mes) VALUES ('2099-01-01')"))
    _rechaza(c, "INSERT INTO avisos_gasto (mes) VALUES ('2099-01-01')")
    _rechaza(c, "INSERT INTO avisos_gasto (mes) VALUES ('2099-01-15')")  # months start on the 1st


def test_an_interest_is_one_row_per_user_and_kind_with_known_kinds_and_bounded_organisation(c):  # noqa: F811
    uid = _usuario(c)
    insertar = "INSERT INTO intereses (usuario_id, tipo, organizacion) VALUES (:u, :t, :o)"
    c.execute(text(insertar), {"u": uid, "t": "paquetes", "o": None})
    c.execute(text(insertar), {"u": uid, "t": "academia", "o": "x" * 120})
    _rechaza(c, insertar, u=uid, t="paquetes", o=None)
    _rechaza(c, insertar, u=_usuario(c), t="otro", o=None)
    _rechaza(c, insertar, u=_usuario(c), t="academia", o="x" * 121)


def test_deleting_the_user_deletes_the_interests(c):  # noqa: F811
    uid = _usuario(c)
    c.execute(text("INSERT INTO intereses (usuario_id, tipo) VALUES (:u, 'paquetes')"), {"u": uid})
    c.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": uid})
    assert c.execute(text("SELECT count(*) FROM intereses WHERE usuario_id = :u"), {"u": uid}).scalar_one() == 0


def test_the_new_foreign_keys_have_the_documented_delete_rule(motor):  # noqa: F811
    reglas = {(t, fk["constrained_columns"][0]): fk["options"].get("ondelete")
              for t in ("gastos_generacion", "intereses") for fk in inspect(motor).get_foreign_keys(t)}
    assert reglas == {("gastos_generacion", "usuario_id"): "SET NULL", ("intereses", "usuario_id"): "CASCADE"}
