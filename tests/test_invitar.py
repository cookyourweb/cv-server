"""scripts/invitar.py: add an invitation to the database.

Runs against the test database (DATABASE_URL_PRUEBAS) inside a rolled-back transaction;
the command-line tests never open a connection.
"""
import importlib.util
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text

import base_de_datos
from test_migracion_0001 import _alembic

RUTA = Path(__file__).resolve().parent.parent / "scripts" / "invitar.py"
_spec = importlib.util.spec_from_file_location("invitar", RUTA)
invitar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(invitar)


@pytest.fixture(scope="module")
def motor(url_de_pruebas):
    _alembic(command.upgrade, "head", url_de_pruebas)
    motor = base_de_datos.crear_motor(url_de_pruebas)
    yield motor
    motor.dispose()


@pytest.fixture
def c(motor):
    with motor.connect() as conexion:
        transaccion = conexion.begin()
        yield conexion
        transaccion.rollback()


def _fila(c, email):
    return c.execute(text("SELECT email, caduca_en > now() AS vigente, caduca_en < now() + interval '8 days' "
                          "AS dentro, usada_en FROM invitaciones WHERE email = :e"), {"e": email}).one()


# --- database ---------------------------------------------------------------------------

@pytest.mark.bd
def test_it_stores_the_email_lowercased_with_the_requested_expiry(c):
    assert invitar.invitar("  Ana@Example.COM ", 7, c) == "ana@example.com"
    fila = _fila(c, "ana@example.com")
    assert fila.vigente and fila.dentro and fila.usada_en is None


@pytest.mark.bd
def test_inviting_again_renews_an_unused_invitation(c):
    invitar.invitar("ana@example.com", 1, c)
    invitar.invitar("ana@example.com", 7, c)
    assert c.execute(text("SELECT count(*) FROM invitaciones")).scalar_one() == 1
    assert _fila(c, "ana@example.com").vigente


@pytest.mark.bd
def test_a_used_invitation_is_not_reopened(c):
    invitar.invitar("ana@example.com", 7, c)
    c.execute(text("UPDATE invitaciones SET usada_en = now()"))
    with pytest.raises(invitar.ErrorDeInvitacion):
        invitar.invitar("ana@example.com", 7, c)


# --- validation (no database) ---------------------------------------------------------------

@pytest.mark.parametrize("email", ["", "sin-arroba", "a@", "@b.com", "a b@c.com", "a@@b.com"])
def test_a_malformed_email_is_rejected_before_any_connection(email):
    with pytest.raises(invitar.ErrorDeInvitacion):
        invitar.invitar(email, 7, conexion=object())


@pytest.mark.parametrize("dias", [0, -1, 366])
def test_the_expiry_must_be_between_one_day_and_a_year(dias):
    with pytest.raises(invitar.ErrorDeInvitacion):
        invitar.invitar("ana@example.com", dias, conexion=object())


def test_the_expiry_option_is_required(capsys):
    with pytest.raises(SystemExit):
        invitar.main(["ana@example.com"])
    assert "--dias" in capsys.readouterr().err


def test_main_without_database_url_fails_without_printing_anything_secret(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert invitar.main(["ana@example.com", "--dias", "7"]) == 1
    salida = capsys.readouterr()
    assert "DATABASE_URL" in salida.err and "postgres" not in (salida.out + salida.err)


def test_main_reports_the_address_and_never_the_url(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario:secreto@host/db")
    monkeypatch.setattr(invitar, "_guardar", lambda email, dias: email.lower())
    assert invitar.main(["Ana@Example.com", "--dias", "7"]) == 0
    salida = capsys.readouterr().out
    assert "ana@example.com" in salida and "secreto" not in salida and "postgresql" not in salida


def test_a_database_error_is_reported_without_the_connection_string(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario:secreto@127.0.0.1:1/db?connect_timeout=1")
    base_de_datos.cerrar()
    try:
        assert invitar.main(["ana@example.com", "--dias", "7"]) == 1
    finally:
        base_de_datos.cerrar()
    salida = capsys.readouterr()
    assert "secreto" not in salida.out + salida.err
