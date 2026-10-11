"""FuenteDeMaster port: where the CV master comes from (Neon first, then Drive).

Order of `resolver_master`: Neon in the requested language -> Drive in that language ->
Neon in the other language (flagged `master_traducido`) -> empty. Without a database the
Neon source is skipped silently, so the legacy Drive flow is untouched.

Pure tests use fakes; the Neon source gets one encrypted round trip against a real
PostgreSQL (DATABASE_URL_PRUEBAS) inside a rolled-back transaction.
"""
import base64
import logging
import os
import uuid

import pytest
from alembic import command
from sqlalchemy import text

import base_de_datos
import cifrado
import fuente_master as fm
from drive import MasterCV
from repositorio import VERSION_DE_CONSENTIMIENTO, RepositorioDeUsuaria
from test_migracion_0001 import _alembic

CANARIO = "CANARIO-CV-5581-no-debe-salir-en-logs"


class BaseFalsa:
    def __init__(self, **por_idioma):
        self.por_idioma = por_idioma
        self.pedidos = []

    def leer(self, idioma):
        self.pedidos.append(idioma)
        return fm.LecturaMaster(self.por_idioma.get(idioma, ""), "", idioma)


def drive_falso(**por_idioma):
    pedidos = []

    def leer(usuario, idioma):
        pedidos.append(idioma)
        return MasterCV(por_idioma.get(idioma, ""), f"https://drive/{idioma}" if por_idioma.get(idioma) else "")
    leer.pedidos = pedidos
    return leer


# --- resolver_master order (pure) ----------------------------------------------------------

def test_neon_in_the_requested_language_wins_and_drive_is_not_touched():
    drive = drive_falso(es="drive es")
    r = fm.resolver_master({}, "es", base=BaseFalsa(es="neon es"), leer_drive=drive)
    assert (r.texto, r.idioma_real, r.master_traducido, r.url) == ("neon es", "es", False, "")
    assert drive.pedidos == []


def test_drive_is_used_when_neon_has_nothing_in_that_language():
    r = fm.resolver_master({}, "es", base=BaseFalsa(), leer_drive=drive_falso(es="drive es"))
    assert (r.texto, r.url, r.idioma_real, r.master_traducido) == ("drive es", "https://drive/es", "es", False)


def test_the_other_neon_language_is_the_last_resort_and_is_flagged():
    r = fm.resolver_master({}, "es", base=BaseFalsa(en="neon en"), leer_drive=drive_falso())
    assert (r.texto, r.idioma_real, r.master_traducido) == ("neon en", "en", True)
    r = fm.resolver_master({}, "en", base=BaseFalsa(es="neon es"), leer_drive=drive_falso())
    assert (r.texto, r.idioma_real, r.master_traducido) == ("neon es", "es", True)


def test_drive_beats_the_other_neon_language():
    r = fm.resolver_master({}, "es", base=BaseFalsa(en="neon en"), leer_drive=drive_falso(es="drive es"))
    assert (r.texto, r.master_traducido) == ("drive es", False)


def test_nothing_anywhere_is_an_empty_master():
    r = fm.resolver_master({}, "es", base=BaseFalsa(), leer_drive=drive_falso())
    assert (r.texto, r.url, r.master_traducido) == ("", "", False)


def test_without_neon_it_is_exactly_the_drive_read():
    drive = drive_falso(en="drive en")
    r = fm.resolver_master({"x": 1}, "en", base=None, leer_drive=drive)
    assert (r.texto, r.url, r.idioma_real, r.master_traducido) == ("drive en", "https://drive/en", "en", False)
    assert drive.pedidos == ["en"]


def test_a_drive_failure_still_propagates_so_the_route_keeps_its_502():
    def roto(usuario, idioma):
        raise RuntimeError("token caducado")
    with pytest.raises(RuntimeError, match="token caducado"):
        fm.resolver_master({}, "es", base=None, leer_drive=roto)


# --- legacy mode: no database -> no Neon source -------------------------------------------

def test_without_database_url_there_is_no_neon_source(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert fm.base_para_email("vero@example.com") is None


def test_a_blank_email_has_no_neon_source(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    assert fm.base_para_email("  ") is None


def test_resolver_master_without_database_never_looks_for_a_user(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = fm.resolver_master({}, "es", email="vero@example.com", leer_drive=drive_falso(es="legacy"))
    assert (r.texto, r.master_traducido) == ("legacy", False)


def test_an_unreachable_database_degrades_to_the_drive_flow(monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:secreto@127.0.0.1:1/x")
    caplog.set_level(logging.DEBUG)
    r = fm.resolver_master({}, "es", email="vero@example.com", leer_drive=drive_falso(es="legacy"))
    assert r.texto == "legacy"
    assert "secreto" not in "\n".join(x.getMessage() for x in caplog.records)


# --- MasterEnBase failure modes (pure) -----------------------------------------------------

class RepoFalso:
    usuario_id = "u-1"

    def __init__(self, fila=None, error=None, consentimiento=True):
        self.fila, self.error, self.consentimiento = fila, error, consentimiento
        self.consultas = []

    def tiene_consentimiento(self, tipo):
        self.consultas.append(tipo)
        return self.consentimiento

    def obtener_cv(self, idioma):
        if self.error:
            raise self.error
        return self.fila


@pytest.fixture
def claves(monkeypatch):
    monkeypatch.setenv("CV_CLAVES", "1:" + base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "1")


def test_no_row_means_empty(claves):
    assert fm.MasterEnBase(RepoFalso()).leer("es") == fm.LecturaMaster("", "", "es")


def test_a_row_that_does_not_authenticate_is_empty_and_logs_nothing_sensitive(claves, caplog):
    version, nonce, cif = cifrado.cifrar(CANARIO, "otro-usuario", "es")
    fila = type("F", (), {"clave_version": version, "nonce": nonce, "cifrado": cif})()
    caplog.set_level(logging.DEBUG)
    assert fm.MasterEnBase(RepoFalso(fila)).leer("es").texto == ""
    from privacidad import volcar_registros
    assert CANARIO not in volcar_registros(caplog.records)


def test_a_repository_error_is_empty_and_logs_only_the_type(caplog):
    caplog.set_level(logging.DEBUG)
    assert fm.MasterEnBase(RepoFalso(error=RuntimeError(CANARIO))).leer("es").texto == ""
    from privacidad import volcar_registros
    volcado = volcar_registros(caplog.records)
    assert CANARIO not in volcado and "RuntimeError" in volcado


def test_a_successful_read_logs_no_content(claves, caplog):
    version, nonce, cif = cifrado.cifrar(CANARIO, "u-1", "es")
    fila = type("F", (), {"clave_version": version, "nonce": nonce, "cifrado": cif})()
    caplog.set_level(logging.DEBUG)
    assert fm.MasterEnBase(RepoFalso(fila)).leer("es").texto == CANARIO
    from privacidad import volcar_registros
    assert CANARIO not in volcar_registros(caplog.records)


# --- AI consent gate (pure) ----------------------------------------------------------------

def _fila(texto, idioma="es"):
    version, nonce, cif = cifrado.cifrar(texto, "u-1", idioma)
    return type("F", (), {"clave_version": version, "nonce": nonce, "cifrado": cif})()


def test_a_master_is_read_when_the_ai_consent_is_active(claves):
    repo = RepoFalso(_fila("con consentimiento"))
    assert fm.MasterEnBase(repo).leer("es").texto == "con consentimiento"
    assert repo.consultas == ["enviar_cv_a_ia"]


def test_a_master_without_the_ai_consent_is_skipped_and_logs_only_a_reason(claves, caplog):
    caplog.set_level(logging.DEBUG)
    repo = RepoFalso(_fila(CANARIO), consentimiento=False)
    assert fm.MasterEnBase(repo).leer("es") == fm.LecturaMaster("", "", "es")
    from privacidad import volcar_registros
    volcado = volcar_registros(caplog.records)
    assert CANARIO not in volcado and "u-1" not in volcado and "consentimiento" in volcado


def test_a_failing_consent_check_fails_closed(claves):
    class Roto(RepoFalso):
        def tiene_consentimiento(self, tipo):
            raise RuntimeError(CANARIO)
    assert fm.MasterEnBase(Roto(_fila(CANARIO))).leer("es").texto == ""


def test_resolution_skips_neon_in_both_languages_without_consent_and_uses_drive(claves):
    base = fm.MasterEnBase(RepoFalso(_fila("neon"), consentimiento=False))
    r = fm.resolver_master({}, "es", base=base, leer_drive=drive_falso(es="drive es"))
    assert (r.texto, r.master_traducido) == ("drive es", False)


def test_the_translated_neon_source_is_gated_too(claves):
    base = fm.MasterEnBase(RepoFalso(_fila("neon en", "en"), consentimiento=False))
    r = fm.resolver_master({}, "es", base=base, leer_drive=drive_falso())
    assert (r.texto, r.master_traducido) == ("", False)


# --- real database ------------------------------------------------------------------------

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


def _usuario(c, email):
    uid = c.execute(text("INSERT INTO usuarios (emisor, sub) VALUES ('https://accounts.google.com', :s) "
                         "RETURNING id"), {"s": uuid.uuid4().hex}).scalar_one()
    c.execute(text("INSERT INTO usuario_emails (email, usuario_id, principal) VALUES (:e, :u, true)"),
              {"e": email, "u": uid})
    return uid


@pytest.mark.bd
def test_neon_round_trip_decrypts_the_stored_master(c, claves):
    uid = _usuario(c, f"{uuid.uuid4().hex}@example.com")
    repo = RepositorioDeUsuaria(c, uid)
    version, nonce, cif = cifrado.cifrar("Frontend senior con Angular", uid, "es")
    repo.guardar_cv("es", "pdf", version, nonce, cif, 27)
    fuente = fm.MasterEnBase(repo)
    assert fuente.leer("es").texto == ""  # stored but no AI consent yet
    repo.registrar_consentimiento("enviar_cv_a_ia", VERSION_DE_CONSENTIMIENTO)
    assert fuente.leer("es") == fm.LecturaMaster("Frontend senior con Angular", "", "es")
    assert fuente.leer("en").texto == ""
    c.execute(text("UPDATE consentimientos SET revocado_en = now() WHERE usuario_id = :u"), {"u": uid})
    assert fuente.leer("es").texto == ""  # revoked


@pytest.mark.bd
def test_the_email_maps_to_the_user_id_and_an_unknown_one_to_none(c):
    email = f"{uuid.uuid4().hex}@example.com"
    uid = _usuario(c, email)
    assert fm.usuario_id_por_email(c, email.upper()) == uid
    assert fm.usuario_id_por_email(c, "nadie@example.com") is None


@pytest.mark.bd
def test_a_row_swapped_to_another_user_does_not_decrypt(c, claves):
    a, b = _usuario(c, f"{uuid.uuid4().hex}@example.com"), _usuario(c, f"{uuid.uuid4().hex}@example.com")
    version, nonce, cif = cifrado.cifrar("secreto de A", a, "es")
    RepositorioDeUsuaria(c, b).guardar_cv("es", "pdf", version, nonce, cif, 12)
    RepositorioDeUsuaria(c, b).registrar_consentimiento("enviar_cv_a_ia", VERSION_DE_CONSENTIMIENTO)
    assert fm.MasterEnBase(RepositorioDeUsuaria(c, b)).leer("es").texto == ""
