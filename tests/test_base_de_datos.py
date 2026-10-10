"""Database access layer: lazy engine, psycopg3 driver, bounded pool.

None of these tests connects to a database: creating an engine is lazy, and the
module itself must be importable without DATABASE_URL (see test_modulos_sin_entorno).
"""
import pytest

import base_de_datos


@pytest.fixture(autouse=True)
def _motor_limpio():
    base_de_datos.cerrar()
    yield
    base_de_datos.cerrar()


@pytest.mark.parametrize("entrada", [
    "postgresql://u:p@host/db?sslmode=require",
    "postgres://u:p@host/db?sslmode=require",
    "postgresql+psycopg://u:p@host/db?sslmode=require",
])
def test_the_url_always_uses_the_psycopg3_driver(entrada):
    assert base_de_datos.url_psycopg(entrada).startswith("postgresql+psycopg://u:p@host/db")


def test_other_drivers_are_rejected():
    with pytest.raises(base_de_datos.ErrorDeBaseDeDatos):
        base_de_datos.url_psycopg("mysql://u:p@host/db")


def test_without_database_url_the_engine_fails_closed(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(base_de_datos.ErrorDeBaseDeDatos):
        base_de_datos.motor()


def test_the_error_never_echoes_the_url(monkeypatch):
    with pytest.raises(base_de_datos.ErrorDeBaseDeDatos) as error:
        base_de_datos.url_psycopg("mysql://usuario:secreto@host/db")
    assert "secreto" not in str(error.value)


def test_the_engine_uses_a_small_validated_recycled_pool(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    pool = base_de_datos.motor().pool
    assert pool.size() == 2
    assert pool._pre_ping is True
    assert pool._recycle == 300


def test_the_engine_is_created_once(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    assert base_de_datos.motor() is base_de_datos.motor()


def test_the_engine_can_be_built_from_an_explicit_url():
    motor = base_de_datos.crear_motor("postgresql://u:p@localhost/db")
    assert motor.dialect.driver == "psycopg"


def _kwargs_del_motor(monkeypatch, url):
    capturado = {}
    monkeypatch.setattr(base_de_datos, "create_engine",
                        lambda destino, **kwargs: capturado.update(kwargs, _url=destino))
    base_de_datos.crear_motor(url)
    return capturado


def test_tls_is_required_when_the_url_has_no_sslmode(monkeypatch):
    kwargs = _kwargs_del_motor(monkeypatch, "postgresql://u:p@host/db")
    assert kwargs["connect_args"] == {"sslmode": "require"}


@pytest.mark.parametrize("modo", ["verify-full", "disable", "require"])
def test_an_explicit_sslmode_in_the_url_is_respected(monkeypatch, modo):
    kwargs = _kwargs_del_motor(monkeypatch, f"postgresql://u:p@host/db?sslmode={modo}")
    assert "sslmode" not in kwargs.get("connect_args", {})
    assert f"sslmode={modo}" in kwargs["_url"]
