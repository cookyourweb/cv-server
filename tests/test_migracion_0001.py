"""Migration 0001_alta against a real PostgreSQL (skipped without DATABASE_URL_PRUEBAS).

The schema tests run inside a transaction that is always rolled back, so they leave
no rows behind. The round-trip test is the only one that changes the schema, and it
always finishes at head.
"""
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

import base_de_datos

pytestmark = pytest.mark.bd

RAIZ = Path(__file__).resolve().parent.parent
TABLAS = {"usuarios", "usuario_emails", "invitaciones", "perfil", "cv_master",
          "extracciones", "consentimientos", "ajustes"}


def _alembic(accion, revision, url):
    from os import environ

    anterior = environ.get("DATABASE_URL")
    environ["DATABASE_URL"] = url
    try:
        accion(Config(str(RAIZ / "alembic.ini")), revision)
    finally:
        if anterior is None:
            environ.pop("DATABASE_URL")
        else:
            environ["DATABASE_URL"] = anterior


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
        yield conexion
        transaccion.rollback()


def _usuario(c, sub=None):
    return c.execute(
        text("INSERT INTO usuarios (emisor, sub, nombre) VALUES ('google', :sub, 'Ada') RETURNING id"),
        {"sub": sub or uuid.uuid4().hex},
    ).scalar_one()


def _rechaza(c, sql, **params):
    """The statement must violate a constraint; a savepoint keeps the transaction usable."""
    with pytest.raises(DBAPIError):
        with c.begin_nested():
            c.execute(text(sql), params)


@pytest.mark.bd_destructiva
def test_upgrade_downgrade_upgrade_is_clean(motor, url_de_pruebas):
    try:
        _alembic(command.downgrade, "base", url_de_pruebas)
        assert TABLAS.isdisjoint(inspect(motor).get_table_names())
        _alembic(command.upgrade, "head", url_de_pruebas)
        assert TABLAS <= set(inspect(motor).get_table_names())
    finally:
        _alembic(command.upgrade, "head", url_de_pruebas)


def test_the_extraction_switch_is_seeded_on(c):
    valor = c.execute(text("SELECT valor FROM ajustes WHERE clave = 'extraccion_activa'")).scalar_one()
    assert valor is True


def test_a_user_gets_a_generated_id_and_timestamp(c):
    fila = c.execute(text(
        "INSERT INTO usuarios (emisor, sub, nombre) VALUES ('google', 'x', 'Ada') RETURNING id, creado_en"
    )).one()
    assert isinstance(fila.id, uuid.UUID) and fila.creado_en is not None


def test_the_issuer_and_subject_pair_is_unique(c):
    _usuario(c, sub="mismo")
    _rechaza(c, "INSERT INTO usuarios (emisor, sub, nombre) VALUES ('google', 'mismo', 'Otra')")


def test_emails_must_be_lowercase(c):
    uid = _usuario(c)
    _rechaza(c, "INSERT INTO usuario_emails (email, usuario_id) VALUES ('Ada@Example.com', :u)", u=uid)


def test_an_email_belongs_to_one_user_only(c):
    c.execute(text("INSERT INTO usuario_emails (email, usuario_id) VALUES ('a@x.com', :u)"), {"u": _usuario(c)})
    _rechaza(c, "INSERT INTO usuario_emails (email, usuario_id) VALUES ('a@x.com', :u)", u=_usuario(c))


def test_invitation_emails_must_be_lowercase(c):
    _rechaza(c, "INSERT INTO invitaciones (email, caduca_en) VALUES ('Ada@X.com', now())")


def test_deleting_the_user_who_used_an_invitation_keeps_it(c):
    uid = _usuario(c)
    c.execute(text("INSERT INTO invitaciones (email, caduca_en, usada_en, usada_por) "
                   "VALUES ('i@x.com', now(), now(), :u)"), {"u": uid})
    c.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": uid})
    assert c.execute(text("SELECT usada_por FROM invitaciones WHERE email = 'i@x.com'")).scalar_one() is None


@pytest.mark.parametrize("columna, valor", [
    ("anios_experiencia", -1),
    ("anios_experiencia", 61),
    ("salario_min", -5),
    ("salario_moneda", "EURO"),
    ("modalidad", "{remoto,teletrabajo}"),
])
def test_the_profile_rejects_out_of_range_values(c, columna, valor):
    uid = _usuario(c)
    destino = f"CAST(:v AS {'text[]' if columna == 'modalidad' else 'text'})"
    if columna in ("anios_experiencia", "salario_min"):
        destino = ":v"
    _rechaza(c, f"INSERT INTO perfil (usuario_id, {columna}) VALUES (:u, {destino})", u=uid, v=valor)


def test_the_profile_accepts_a_complete_valid_row(c):
    uid = _usuario(c)
    c.execute(text(
        "INSERT INTO perfil (usuario_id, rol, anios_experiencia, stack, idiomas, ubicacion, modalidad, "
        "salario_min, salario_moneda) VALUES (:u, 'Frontend', 20, '{angular,typescript}', '{es,en}', "
        "'Madrid', '{remoto,hibrido}', 50000, 'EUR')"), {"u": uid})
    fila = c.execute(text("SELECT origen, actualizado_en FROM perfil WHERE usuario_id = :u"), {"u": uid}).one()
    assert fila.origen == {} and fila.actualizado_en is not None


@pytest.mark.parametrize("sql", [
    "INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, caracteres) "
    "VALUES (:u, 'fr', 'pdf', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)",
    "INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, caracteres) "
    "VALUES (:u, 'es', 'odt', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)",
    "INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, caracteres) "
    "VALUES (:u, 'es', 'pdf', 1, decode(repeat('00', 11), 'hex'), '\\x01', 10)",
])
def test_the_cv_master_rejects_bad_language_format_or_nonce(c, sql):
    _rechaza(c, sql, u=_usuario(c))


def test_one_cv_per_user_and_language(c):
    uid = _usuario(c)
    insertar = ("INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, caracteres) "
                "VALUES (:u, :i, 'pdf', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)")
    c.execute(text(insertar), {"u": uid, "i": "es"})
    c.execute(text(insertar), {"u": uid, "i": "en"})
    _rechaza(c, insertar, u=uid, i="es")


def _extraccion(estado, uid):
    return text("INSERT INTO extracciones (usuario_id, modelo, estado, estimado_eur) "
                "VALUES (:u, 'sonnet', :e, 0.05)"), {"u": uid, "e": estado}


def test_an_extraction_state_must_be_known(c):
    sql, params = _extraccion("rara", _usuario(c))
    with pytest.raises(IntegrityError):
        with c.begin_nested():
            c.execute(sql, params)


def test_a_second_extraction_is_allowed_only_after_a_failed_one(c):
    uid = _usuario(c)
    c.execute(*_extraccion("fallida", uid))
    c.execute(*_extraccion("completada", uid))
    sql, params = _extraccion("reservada", uid)
    with pytest.raises(IntegrityError):
        with c.begin_nested():
            c.execute(sql, params)


def test_failed_extractions_can_repeat_and_orphans_are_not_limited(c):
    uid = _usuario(c)
    c.execute(*_extraccion("fallida", uid))
    c.execute(*_extraccion("fallida", uid))
    for _ in range(2):
        c.execute(*_extraccion("completada", None))


def test_consent_type_must_be_known(c):
    _rechaza(c, "INSERT INTO consentimientos (usuario_id, tipo, version) VALUES (:u, 'otro', 'v1')",
             u=_usuario(c))


def test_a_consent_version_is_recorded_once_per_user_and_type(c):
    uid = _usuario(c)
    insertar = "INSERT INTO consentimientos (usuario_id, tipo, version) VALUES (:u, :t, 'v1')"
    c.execute(text(insertar), {"u": uid, "t": "almacenar_cv"})
    c.execute(text(insertar), {"u": uid, "t": "enviar_cv_a_ia"})
    _rechaza(c, insertar, u=uid, t="almacenar_cv")


def test_deleting_a_user_cascades_and_keeps_the_extraction_ledger(c):
    uid = _usuario(c)
    c.execute(text("INSERT INTO usuario_emails (email, usuario_id) VALUES ('c@x.com', :u)"), {"u": uid})
    c.execute(text("INSERT INTO perfil (usuario_id, rol) VALUES (:u, 'Dev')"), {"u": uid})
    c.execute(text("INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, "
                   "caracteres) VALUES (:u, 'es', 'pdf', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)"),
              {"u": uid})
    c.execute(text("INSERT INTO consentimientos (usuario_id, tipo, version) VALUES (:u, 'almacenar_cv', 'v1')"),
              {"u": uid})
    c.execute(*_extraccion("completada", uid))

    c.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": uid})

    for tabla in ("usuario_emails", "perfil", "cv_master", "consentimientos"):
        assert c.execute(text(f"SELECT count(*) FROM {tabla} WHERE usuario_id = :u"), {"u": uid}).scalar_one() == 0
    fila = c.execute(text("SELECT usuario_id FROM extracciones WHERE estado = 'completada' "
                          "AND modelo = 'sonnet' ORDER BY creada_en DESC LIMIT 1")).one()
    assert fila.usuario_id is None


def test_every_foreign_key_has_the_documented_delete_rule(motor):
    reglas = {}
    for tabla in TABLAS:
        for fk in inspect(motor).get_foreign_keys(tabla):
            reglas[(tabla, fk["constrained_columns"][0])] = fk["options"].get("ondelete")
    assert reglas == {
        ("usuario_emails", "usuario_id"): "CASCADE",
        ("perfil", "usuario_id"): "CASCADE",
        ("cv_master", "usuario_id"): "CASCADE",
        ("consentimientos", "usuario_id"): "CASCADE",
        ("invitaciones", "usada_por"): "SET NULL",
        ("extracciones", "usuario_id"): "SET NULL",
    }


def test_the_transaction_helper_commits_and_rolls_back(motor, url_de_pruebas, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", url_de_pruebas)
    base_de_datos.cerrar()
    sub = uuid.uuid4().hex
    try:
        with pytest.raises(RuntimeError):
            with base_de_datos.transaccion() as conexion:
                conexion.execute(text("INSERT INTO usuarios (emisor, sub, nombre) VALUES ('google', :s, 'x')"),
                                 {"s": sub})
                raise RuntimeError("boom")
        with motor.connect() as conexion:
            assert conexion.execute(text("SELECT count(*) FROM usuarios WHERE sub = :s"), {"s": sub}).scalar_one() == 0
    finally:
        base_de_datos.cerrar()
