"""Identity and invitations: a verified Google (iss, sub) maps to an internal user id.

These tests run against a real PostgreSQL (DATABASE_URL_PRUEBAS). Each one works inside
a transaction that is rolled back at the end, so nothing is left behind.
"""
import uuid

import pytest
from alembic import command
from sqlalchemy import text

import base_de_datos
import usuarias
from autenticacion import Identidad
from test_migracion_0001 import _alembic

pytestmark = pytest.mark.bd

EMISOR = "https://accounts.google.com"


@pytest.fixture(scope="module")
def motor(url_de_pruebas):
    _alembic(command.upgrade, "head", url_de_pruebas)
    motor = base_de_datos.crear_motor(url_de_pruebas)
    yield motor
    motor.dispose()


@pytest.fixture
def c(motor):
    """A connection whose work is rolled back at the end of the test."""
    with motor.connect() as conexion:
        transaccion = conexion.begin()
        # The test branch is shared with manual trials. Start each test from empty
        # tables inside this transaction; the rollback brings any trial rows back.
        conexion.execute(text("DELETE FROM usuarios"))
        conexion.execute(text("DELETE FROM invitaciones"))
        yield conexion
        transaccion.rollback()


def _identidad(email="ana@example.com", sub=None, emisor=EMISOR, nombre="Ana"):
    return Identidad(emisor, sub or uuid.uuid4().hex, email, nombre)


def _invitar(c, email, caduca="now() + interval '7 days'", usada=False):
    c.execute(text(f"INSERT INTO invitaciones (email, caduca_en) VALUES (:e, {caduca})"), {"e": email})
    if usada:
        c.execute(text("UPDATE invitaciones SET usada_en = now() WHERE email = :e"), {"e": email})


def _cuenta(c, tabla):
    return c.execute(text(f"SELECT count(*) FROM {tabla}")).scalar_one()


def _estado(c):
    return tuple(_cuenta(c, t) for t in ("usuarios", "usuario_emails", "invitaciones"))


# --- S1.1 ---------------------------------------------------------------------

def test_first_sign_in_with_an_invitation_creates_the_user_and_consumes_it(c):
    _invitar(c, "ana@example.com")
    quien = _identidad()
    uid = usuarias.resolver_o_crear(quien, c)
    assert isinstance(uid, uuid.UUID)
    fila = c.execute(text("SELECT emisor, sub, nombre FROM usuarios WHERE id = :u"), {"u": uid}).one()
    assert (fila.emisor, fila.sub, fila.nombre) == (EMISOR, quien.sub, "Ana")
    correo = c.execute(text("SELECT usuario_id, principal FROM usuario_emails WHERE email = 'ana@example.com'")).one()
    assert (correo.usuario_id, correo.principal) == (uid, True)
    inv = c.execute(text("SELECT usada_en, usada_por FROM invitaciones WHERE email = 'ana@example.com'")).one()
    assert inv.usada_en is not None and inv.usada_por == uid


def test_the_email_case_does_not_matter(c):
    _invitar(c, "ana@example.com")
    assert usuarias.resolver_o_crear(_identidad(email="  Ana@Example.COM "), c) is not None


def test_signing_in_again_returns_the_same_user_without_new_rows(c):
    _invitar(c, "ana@example.com")
    quien = _identidad()
    primero = usuarias.resolver_o_crear(quien, c)
    antes = _estado(c)
    assert usuarias.resolver_o_crear(quien, c) == primero
    assert _estado(c) == antes


# --- S1.2 ---------------------------------------------------------------------

def test_a_second_invited_mailbox_of_the_same_account_is_added_without_a_new_user(c):
    _invitar(c, "ana@example.com")
    _invitar(c, "ana.trabajo@example.com")
    quien = _identidad()
    uid = usuarias.resolver_o_crear(quien, c)
    segundo = usuarias.resolver_o_crear(
        Identidad(EMISOR, quien.sub, "ana.trabajo@example.com", "Ana"), c)
    assert segundo == uid
    assert _cuenta(c, "usuarios") == 1
    filas = c.execute(text("SELECT email, principal FROM usuario_emails ORDER BY email")).all()
    assert [(f.email, f.principal) for f in filas] == [
        ("ana.trabajo@example.com", False), ("ana@example.com", True)]
    assert c.execute(text("SELECT usada_por FROM invitaciones WHERE email = 'ana.trabajo@example.com'")
                     ).scalar_one() == uid


def test_a_known_account_with_an_uninvited_new_mailbox_signs_in_with_no_writes(c):
    _invitar(c, "ana@example.com")
    quien = _identidad()
    uid = usuarias.resolver_o_crear(quien, c)
    antes = _estado(c)
    assert usuarias.resolver_o_crear(Identidad(EMISOR, quien.sub, "otro@example.com", "Ana"), c) == uid
    assert _estado(c) == antes


# --- S1.3 ---------------------------------------------------------------------

def test_without_an_invitation_access_is_denied_with_no_writes(c):
    antes = _estado(c)
    assert usuarias.resolver_o_crear(_identidad(), c) is None
    assert _estado(c) == antes


@pytest.mark.parametrize("caducidad, usada", [
    ("now() - interval '1 minute'", False),
    ("now() + interval '7 days'", True),
])
def test_an_expired_or_used_invitation_does_not_open_the_door(c, caducidad, usada):
    _invitar(c, "ana@example.com", caduca=caducidad, usada=usada)
    antes = _estado(c)
    assert usuarias.resolver_o_crear(_identidad(), c) is None
    assert _estado(c) == antes


def test_an_invitation_is_consumed_only_once(c):
    _invitar(c, "ana@example.com")
    assert usuarias.resolver_o_crear(_identidad(sub="uno"), c) is not None
    assert usuarias.resolver_o_crear(_identidad(sub="dos"), c) is None
    assert _cuenta(c, "usuarios") == 1


# --- S1.5 ---------------------------------------------------------------------

def test_a_matching_email_with_a_different_subject_is_not_merged(c):
    _invitar(c, "ana@example.com")
    owner = usuarias.resolver_o_crear(_identidad(sub="the-owner"), c)
    # Even if the address is invited again, a different subject must not take the account.
    c.execute(text("UPDATE invitaciones SET usada_en = NULL, usada_por = NULL WHERE email = 'ana@example.com'"))
    antes = _estado(c)
    assert usuarias.resolver_o_crear(_identidad(sub="someone-else"), c) is None
    assert _estado(c) == antes
    assert c.execute(text("SELECT usuario_id FROM usuario_emails WHERE email = 'ana@example.com'")
                     ).scalar_one() == owner


def test_the_same_subject_from_another_issuer_is_a_different_user(c):
    _invitar(c, "ana@example.com")
    _invitar(c, "bea@example.com")
    uno = usuarias.resolver_o_crear(_identidad(sub="42"), c)
    dos = usuarias.resolver_o_crear(_identidad(email="bea@example.com", sub="42", emisor="https://otro"), c)
    assert uno is not None and dos is not None and uno != dos


# --- bootstrap fallback ---------------------------------------------------------

def test_the_bootstrap_fallback_admits_a_listed_email_without_an_invitation(c):
    uid = usuarias.resolver_o_crear(_identidad(), c, respaldo=frozenset({"ana@example.com"}))
    assert uid is not None
    assert _cuenta(c, "usuario_emails") == 1


def test_the_fallback_does_not_admit_an_email_that_is_not_listed(c):
    assert usuarias.resolver_o_crear(_identidad(), c, respaldo=frozenset({"otra@example.com"})) is None


def test_without_the_fallback_a_listed_email_is_still_denied(c):
    assert usuarias.resolver_o_crear(_identidad(), c) is None


# --- profile and master lookups ---------------------------------------------------

def test_has_profile_and_master_report_what_neon_holds(c):
    _invitar(c, "ana@example.com")
    uid = usuarias.resolver_o_crear(_identidad(), c)
    assert usuarias.tiene_perfil(uid, c) is False and usuarias.tiene_master(uid, c) is False
    c.execute(text("INSERT INTO perfil (usuario_id, rol) VALUES (:u, 'Dev')"), {"u": uid})
    assert usuarias.tiene_perfil(uid, c) is True
    c.execute(text("INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, "
                   "caracteres) VALUES (:u, 'es', 'pdf', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)"),
              {"u": uid})
    assert usuarias.tiene_master(uid, c) is True


def test_a_database_failure_surfaces_as_one_domain_error(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db?connect_timeout=1")
    base_de_datos.cerrar()
    try:
        with pytest.raises(usuarias.BaseDeDatosNoDisponible) as error:
            usuarias.resolver_o_crear(_identidad())
    finally:
        base_de_datos.cerrar()
    assert "127.0.0.1" not in str(error.value)
