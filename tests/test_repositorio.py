"""Owner-scoped repository: profile, consent and account deletion.

REQ-1.4: every method is scoped by the id given to the constructor and none accepts
another user's id. REQ-2.1..2.5: consent is stored with version and timestamp, an old
version does not authorise, and deletion is one transaction.

Database tests (marked bd) run inside a transaction that is rolled back at the end.
"""
import inspect
import uuid

import pytest
from alembic import command
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import base_de_datos
from repositorio import (
    TIPOS_DE_CONSENTIMIENTO, VERSION_DE_CONSENTIMIENTO, PerfilEntrada, RepositorioDeUsuaria,
)
from test_migracion_0001 import _alembic

PERFIL = {
    "rol": "Frontend developer", "anios_experiencia": 12, "stack": ["Angular", "TypeScript"],
    "idiomas": ["es", "en"], "ubicacion": "Madrid", "modalidad": ["remoto", "hibrido"],
    "salario_min": 45000, "salario_moneda": "EUR",
}


# --- input validation (pure) ----------------------------------------------------------

def test_a_complete_profile_is_accepted():
    assert PerfilEntrada(**PERFIL).anios_experiencia == 12


def test_surrounding_whitespace_is_trimmed_and_the_currency_is_upper_cased():
    perfil = PerfilEntrada(**{**PERFIL, "rol": "  Dev  ", "salario_moneda": " eur "})
    assert perfil.rol == "Dev" and perfil.salario_moneda == "EUR"


@pytest.mark.parametrize("cambio", [
    {"extra": 1},                                   # unknown field
    {"anios_experiencia": 61},                      # table CHECK 0..60
    {"anios_experiencia": -1},
    {"anios_experiencia": 3.5},
    {"modalidad": ["remoto", "volando"]},           # subset of remoto/hibrido/presencial
    {"salario_min": -1},                            # table CHECK >= 0
    {"salario_moneda": "EU"},                       # char(3)
    {"salario_moneda": "EURO"},
    {"salario_moneda": "E1R"},
    {"rol": ""},
    {"rol": "x" * 201},
    {"stack": ["x"] * 51},
    {"stack": ["x" * 81]},
    {"stack": "Angular"},                           # not a list
    {"idiomas": [""]},
    {"ubicacion": "x" * 201},
])
def test_invalid_profiles_are_rejected(cambio):
    with pytest.raises(ValidationError):
        PerfilEntrada(**{**PERFIL, **cambio})


@pytest.mark.parametrize("campo", sorted(PERFIL))
def test_every_field_is_required(campo):
    # The panel always sends all of them and reads them all back.
    datos = {k: v for k, v in PERFIL.items() if k != campo}
    with pytest.raises(ValidationError):
        PerfilEntrada(**datos)


def test_no_method_accepts_another_users_id():
    """REQ-1.4: the owner is the constructor's id; there is no way to name another."""
    metodos = [m for n, m in inspect.getmembers(RepositorioDeUsuaria, inspect.isfunction)
               if not n.startswith("_")]
    assert metodos, "the repository exposes no public methods?"
    for metodo in metodos:
        for nombre in inspect.signature(metodo).parameters:
            assert "usuari" not in nombre and nombre not in {"id", "uid", "owner", "propietaria"}, metodo


def test_the_consent_version_matches_the_panel_constant():
    assert VERSION_DE_CONSENTIMIENTO == "v2"
    assert set(TIPOS_DE_CONSENTIMIENTO) == {"almacenar_cv", "enviar_cv_a_ia"}


# --- database ---------------------------------------------------------------------------

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


def _usuaria(c, nombre="Ana") -> uuid.UUID:
    uid = c.execute(text("INSERT INTO usuarios (emisor, sub, nombre) VALUES ('https://e', :s, :n) "
                         "RETURNING id"), {"s": uuid.uuid4().hex, "n": nombre}).scalar_one()
    c.execute(text("INSERT INTO usuario_emails (email, usuario_id, principal) VALUES (:e, :u, true)"),
              {"e": f"{uid.hex}@example.com", "u": uid})
    return uid


def _cuenta(c, tabla, uid=None):
    if uid is None:
        return c.execute(text(f"SELECT count(*) FROM {tabla}")).scalar_one()
    columna = "id" if tabla == "usuarios" else "usuario_id"
    return c.execute(text(f"SELECT count(*) FROM {tabla} WHERE {columna} = :u"), {"u": uid}).scalar_one()


def _rellenar(c, uid):
    """Give a user a row in every table the deletion must clear, plus a ledger row."""
    RepositorioDeUsuaria(c, uid).guardar_perfil(PerfilEntrada(**PERFIL))
    RepositorioDeUsuaria(c, uid).registrar_consentimiento("almacenar_cv", VERSION_DE_CONSENTIMIENTO)
    c.execute(text("INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, "
                   "caracteres) VALUES (:u, 'es', 'pdf', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)"),
              {"u": uid})
    c.execute(text("INSERT INTO extracciones (usuario_id, modelo, estado, estimado_eur) "
                   "VALUES (:u, 'prueba', 'completada', 0.04)"), {"u": uid})
    RepositorioDeUsuaria(c, uid).registrar_interes("academia", "Academia Prueba")
    c.execute(text("INSERT INTO gastos_generacion (usuario_id, tipo, modelo, unidades, estado, coste_estimado) "
                   "VALUES (:u, 'cv', 'prueba', 0.7, 'completada', 0.02)"), {"u": uid})


@pytest.mark.bd
def test_there_is_no_profile_until_one_is_saved(c):
    assert RepositorioDeUsuaria(c, _usuaria(c)).obtener_perfil() is None


@pytest.mark.bd
def test_a_saved_profile_reads_back_in_the_wire_format(c):
    repo = RepositorioDeUsuaria(c, _usuaria(c))
    repo.guardar_perfil(PerfilEntrada(**PERFIL))
    assert repo.obtener_perfil() == PERFIL


@pytest.mark.bd
def test_saving_again_replaces_the_profile(c):
    repo = RepositorioDeUsuaria(c, _usuaria(c))
    repo.guardar_perfil(PerfilEntrada(**PERFIL))
    repo.guardar_perfil(PerfilEntrada(**{**PERFIL, "rol": "Tech lead", "modalidad": []}))
    leido = repo.obtener_perfil()
    assert leido["rol"] == "Tech lead" and leido["modalidad"] == []
    assert _cuenta(c, "perfil", repo._usuario_id) == 1


@pytest.mark.bd
def test_one_user_never_sees_or_changes_another_users_profile(c):
    a, b = _usuaria(c, "A"), _usuaria(c, "B")
    RepositorioDeUsuaria(c, b).guardar_perfil(PerfilEntrada(**PERFIL))
    assert RepositorioDeUsuaria(c, a).obtener_perfil() is None
    RepositorioDeUsuaria(c, a).guardar_perfil(PerfilEntrada(**{**PERFIL, "rol": "Other"}))
    assert RepositorioDeUsuaria(c, b).obtener_perfil()["rol"] == PERFIL["rol"]


# --- consent: REQ-2.1, REQ-2.2 --------------------------------------------------------------

@pytest.mark.bd
def test_consent_is_stored_with_its_version_and_a_timestamp(c):
    uid = _usuaria(c)
    RepositorioDeUsuaria(c, uid).registrar_consentimiento("enviar_cv_a_ia", VERSION_DE_CONSENTIMIENTO)
    fila = c.execute(text("SELECT tipo, version, otorgado_en, revocado_en FROM consentimientos "
                          "WHERE usuario_id = :u"), {"u": uid}).one()
    assert (fila.tipo, fila.version) == ("enviar_cv_a_ia", VERSION_DE_CONSENTIMIENTO)
    assert fila.otorgado_en is not None and fila.revocado_en is None


@pytest.mark.bd
def test_recording_the_same_consent_twice_keeps_one_row(c):
    uid = _usuaria(c)
    repo = RepositorioDeUsuaria(c, uid)
    repo.registrar_consentimiento("almacenar_cv", VERSION_DE_CONSENTIMIENTO)
    primera = c.execute(text("SELECT otorgado_en FROM consentimientos WHERE usuario_id = :u"),
                        {"u": uid}).scalar_one()
    repo.registrar_consentimiento("almacenar_cv", VERSION_DE_CONSENTIMIENTO)
    assert _cuenta(c, "consentimientos", uid) == 1
    assert c.execute(text("SELECT otorgado_en FROM consentimientos WHERE usuario_id = :u"),
                     {"u": uid}).scalar_one() == primera


@pytest.mark.bd
def test_the_current_consent_authorises_and_a_missing_one_does_not(c):
    repo = RepositorioDeUsuaria(c, _usuaria(c))
    assert repo.tiene_consentimiento("enviar_cv_a_ia") is False
    repo.registrar_consentimiento("enviar_cv_a_ia", VERSION_DE_CONSENTIMIENTO)
    assert repo.tiene_consentimiento("enviar_cv_a_ia") is True
    assert repo.tiene_consentimiento("almacenar_cv") is False  # a different type


@pytest.mark.bd
def test_S2_2_an_old_consent_version_does_not_authorise(c):
    uid = _usuaria(c)
    c.execute(text("INSERT INTO consentimientos (usuario_id, tipo, version) VALUES (:u, 'enviar_cv_a_ia', 'v0')"),
              {"u": uid})
    assert RepositorioDeUsuaria(c, uid).tiene_consentimiento("enviar_cv_a_ia") is False


@pytest.mark.bd
def test_a_revoked_consent_does_not_authorise(c):
    uid = _usuaria(c)
    repo = RepositorioDeUsuaria(c, uid)
    repo.registrar_consentimiento("enviar_cv_a_ia", VERSION_DE_CONSENTIMIENTO)
    c.execute(text("UPDATE consentimientos SET revocado_en = now() WHERE usuario_id = :u"), {"u": uid})
    assert repo.tiene_consentimiento("enviar_cv_a_ia") is False


@pytest.mark.bd
def test_one_users_consent_does_not_authorise_another(c):
    a, b = _usuaria(c, "A"), _usuaria(c, "B")
    RepositorioDeUsuaria(c, a).registrar_consentimiento("enviar_cv_a_ia", VERSION_DE_CONSENTIMIENTO)
    assert RepositorioDeUsuaria(c, b).tiene_consentimiento("enviar_cv_a_ia") is False


# --- deletion: S2.3, S2.4, S2.5, S2.7 -------------------------------------------------------------

@pytest.mark.bd
def test_S2_3_deleting_the_account_clears_every_owned_row_and_keeps_the_anonymous_ledger(c):
    uid = _usuaria(c)
    _rellenar(c, uid)
    assert RepositorioDeUsuaria(c, uid).borrar_cuenta() is True
    for tabla in ("usuarios", "usuario_emails", "perfil", "cv_master", "consentimientos", "intereses"):
        assert _cuenta(c, tabla, uid) == 0, tabla
    huerfana = c.execute(text("SELECT usuario_id, estimado_eur FROM extracciones WHERE modelo = 'prueba'")).one()
    assert huerfana.usuario_id is None and float(huerfana.estimado_eur) == 0.04
    # The generation ledger stays too, anonymous: deleting an account cannot reset the monthly cap.
    gasto = c.execute(text("SELECT usuario_id, coste_estimado FROM gastos_generacion WHERE modelo = 'prueba'")).one()
    assert gasto.usuario_id is None and float(gasto.coste_estimado) == 0.02


@pytest.mark.bd
def test_deleting_an_account_that_is_already_gone_reports_it(c):
    uid = _usuaria(c)
    repo = RepositorioDeUsuaria(c, uid)
    assert repo.borrar_cuenta() is True
    assert repo.borrar_cuenta() is False


@pytest.mark.bd
def test_S2_5_deleting_one_account_leaves_the_other_untouched(c):
    a, b = _usuaria(c, "A"), _usuaria(c, "B")
    _rellenar(c, a)
    _rellenar(c, b)
    RepositorioDeUsuaria(c, a).borrar_cuenta()
    for tabla in ("usuarios", "usuario_emails", "perfil", "cv_master", "consentimientos", "extracciones",
                  "intereses", "gastos_generacion"):
        assert _cuenta(c, tabla, b) == 1, tabla


@pytest.mark.bd
def test_S2_4_a_failure_midway_leaves_every_row_in_place(c, monkeypatch):
    uid = _usuaria(c)
    _rellenar(c, uid)

    def cae(self):
        raise OperationalError("DELETE", {}, Exception("injected"))
    # The last step fails after the earlier deletions have already run in the transaction.
    monkeypatch.setattr(RepositorioDeUsuaria, "_eliminar_usuaria", cae)
    with pytest.raises(OperationalError):
        with c.begin_nested():
            RepositorioDeUsuaria(c, uid).borrar_cuenta()
    for tabla in ("usuarios", "usuario_emails", "perfil", "cv_master", "consentimientos", "extracciones",
                  "intereses", "gastos_generacion"):
        assert _cuenta(c, tabla, uid) == 1, tabla
