"""Owner-scoped HTTP routes of the sign-up flow: /perfil, /consentimientos and /cuenta.

Wire format taken from the panel (panel-empleo: repositorio-de-perfil-http.ts,
repositorio-de-cuenta-http.ts): snake_case fields, PUT /perfil answers 2xx, GET /perfil
answers 404 when there is no profile, consents are posted as {tipo, version}.

Database mode runs against a real PostgreSQL (DATABASE_URL_PRUEBAS) with real signed
tokens (throwaway key) and cleans up everything it created. No Notion, Drive or Google.
"""
import logging

import pytest
import rsa
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import base_de_datos
import server as srv
from autenticacion import ClavesPublicas, ConfiguracionOIDC
from repositorio import RepositorioDeUsuaria
from test_autenticacion import AUDIENCIA, EMISOR, Descargador, Reloj, _firmar, _jwks, _payload
from test_migracion_0001 import _alembic

PERFIL = {
    "rol": "Frontend developer", "anios_experiencia": 12, "stack": ["Angular", "TypeScript"],
    "idiomas": ["es", "en"], "ubicacion": "Madrid", "modalidad": ["remoto", "hibrido"],
    "salario_min": 45000, "salario_moneda": "EUR",
}
CONSENTIMIENTO = {"tipo": "enviar_cv_a_ia", "version": "v1"}

# Every route behind @con_usuaria that owns data. A new route in the blueprint must be
# added here, which puts it under the cross-user (S1.6) and the no-token tests.
RUTAS_PROPIAS = {
    ("GET", "/perfil"): None,
    ("PUT", "/perfil"): PERFIL,
    ("POST", "/consentimientos"): CONSENTIMIENTO,
    ("DELETE", "/cuenta"): None,
    ("POST", "/cv"): None,
    ("GET", "/cv"): None,
    ("DELETE", "/cv/<idioma>"): None,
}
CORREOS = [f"{n}@ejemplo.es" for n in ("ana", "bea", "carla")]


class Persona:
    def __init__(self, nombre: str, par):
        self.sub = f"rutas-{nombre}"
        self.email = f"{nombre}@ejemplo.es"
        self._par = par

    @property
    def cabeceras(self):
        token = _firmar(self._par[1], _payload(sub=self.sub, email=self.email, name=self.email))
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def par():
    return rsa.newkeys(1024)


@pytest.fixture(scope="module")
def migrado(url_de_pruebas):
    _alembic(command.upgrade, "head", url_de_pruebas)


def _limpiar():
    with base_de_datos.transaccion() as c:
        c.execute(text("DELETE FROM usuarios WHERE emisor = :e"), {"e": EMISOR})
        c.execute(text("DELETE FROM invitaciones WHERE email = ANY(:c)"), {"c": CORREOS})
        c.execute(text("DELETE FROM extracciones WHERE modelo = 'prueba-rutas'"))


@pytest.fixture
def bd(monkeypatch, par, url_de_pruebas, migrado):
    """Server in database mode with a throwaway key; the database is cleaned afterwards."""
    monkeypatch.setattr(srv, "CONFIG_OIDC", ConfiguracionOIDC(AUDIENCIA, (EMISOR,), "https://jwks", frozenset()))
    monkeypatch.setattr(srv, "CLAVES", ClavesPublicas("https://jwks", Descargador(_jwks(k1=par[0])), reloj=Reloj()))
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda email: None)
    monkeypatch.setenv("DATABASE_URL", url_de_pruebas)
    base_de_datos.cerrar()
    _limpiar()
    yield monkeypatch
    _limpiar()
    base_de_datos.cerrar()


@pytest.fixture
def cliente(bd):
    with srv.app.test_client() as c:
        yield c


@pytest.fixture
def personas(bd, par):
    """Ana, Bea and Carla: invited, so their first request creates the user."""
    gente = {n: Persona(n, par) for n in ("ana", "bea", "carla")}
    with base_de_datos.transaccion() as c:
        for p in gente.values():
            c.execute(text("INSERT INTO invitaciones (email, caduca_en) VALUES (:e, now() + interval '7 days')"),
                      {"e": p.email})
    return gente


def _llamar(cliente, metodo, ruta, persona, cuerpo=None):
    return cliente.open(ruta.replace("<idioma>", "es"), method=metodo, headers=persona.cabeceras, json=cuerpo)


def _usuario_id(persona):
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT usuario_id FROM usuario_emails WHERE email = :e"),
                         {"e": persona.email}).scalar_one()


def _filas(tabla, persona):
    columna = "id" if tabla == "usuarios" else "usuario_id"
    with base_de_datos.transaccion() as c:
        return c.execute(text(f"SELECT count(*) FROM {tabla} WHERE {columna} = :u"),
                         {"u": _usuario_id(persona)}).scalar_one()


# --- inventory ---------------------------------------------------------------------------

def test_the_blueprint_routes_are_exactly_the_documented_owner_routes():
    registradas = {(metodo, regla.rule)
                   for regla in srv.app.url_map.iter_rules() if regla.endpoint.startswith("alta.")
                   for metodo in regla.methods - {"HEAD", "OPTIONS"}}
    assert registradas == set(RUTAS_PROPIAS)


@pytest.mark.parametrize("metodo, ruta", sorted(RUTAS_PROPIAS))
def test_every_owner_route_needs_a_token(cliente, metodo, ruta):
    assert cliente.open(ruta, method=metodo, json=RUTAS_PROPIAS[(metodo, ruta)]).status_code == 401


# --- GET and PUT /perfil ------------------------------------------------------------------

def test_there_is_no_profile_until_one_is_saved(cliente, personas):
    r = _llamar(cliente, "GET", "/perfil", personas["ana"])
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "no encontrado"}


def test_a_saved_profile_is_returned_as_the_panel_sent_it(cliente, personas):
    r = _llamar(cliente, "PUT", "/perfil", personas["ana"], PERFIL)
    assert r.status_code == 200 and r.get_json() == PERFIL
    leido = _llamar(cliente, "GET", "/perfil", personas["ana"])
    assert leido.status_code == 200 and leido.get_json() == PERFIL


def test_putting_again_replaces_the_profile(cliente, personas):
    _llamar(cliente, "PUT", "/perfil", personas["ana"], PERFIL)
    _llamar(cliente, "PUT", "/perfil", personas["ana"], {**PERFIL, "rol": "Tech lead", "modalidad": ["presencial"]})
    leido = _llamar(cliente, "GET", "/perfil", personas["ana"]).get_json()
    assert leido["rol"] == "Tech lead" and leido["modalidad"] == ["presencial"]
    assert _filas("perfil", personas["ana"]) == 1


@pytest.mark.parametrize("cambio", [
    {"extra": 1}, {"anios_experiencia": 61}, {"anios_experiencia": "12"}, {"modalidad": ["volando"]},
    {"salario_min": -1}, {"salario_moneda": "EU"}, {"rol": ""}, {"stack": "Angular"},
])
def test_an_invalid_profile_is_a_422_and_stores_nothing(cliente, personas, cambio):
    r = _llamar(cliente, "PUT", "/perfil", personas["ana"], {**PERFIL, **cambio})
    assert r.status_code == 422 and r.get_json()["ok"] is False
    assert _llamar(cliente, "GET", "/perfil", personas["ana"]).status_code == 404


def test_a_missing_field_is_a_422(cliente, personas):
    sin_rol = {k: v for k, v in PERFIL.items() if k != "rol"}
    r = _llamar(cliente, "PUT", "/perfil", personas["ana"], sin_rol)
    assert r.status_code == 422 and r.get_json()["campos"] == ["rol"]


@pytest.mark.parametrize("cuerpo", [None, [], "texto", 5])
def test_a_body_that_is_not_an_object_is_a_422(cliente, personas, cuerpo):
    assert _llamar(cliente, "PUT", "/perfil", personas["ana"], cuerpo).status_code == 422


def test_validation_errors_never_echo_the_submitted_values(cliente, personas):
    r = _llamar(cliente, "PUT", "/perfil", personas["ana"], {**PERFIL, "rol": "", "ubicacion": "SECRETO-CIUDAD",
                                                              "extra": "SECRETO-EXTRA"})
    cuerpo = r.get_data(as_text=True)
    assert r.status_code == 422 and "SECRETO" not in cuerpo


# --- POST /consentimientos -----------------------------------------------------------------

def test_a_consent_is_created_with_201_and_stored_with_its_version(cliente, personas):
    r = _llamar(cliente, "POST", "/consentimientos", personas["ana"], CONSENTIMIENTO)
    assert r.status_code == 201
    assert r.get_json()["tipo"] == "enviar_cv_a_ia" and r.get_json()["version"] == "v1"
    with base_de_datos.transaccion() as c:
        fila = c.execute(text("SELECT tipo, version, otorgado_en FROM consentimientos WHERE usuario_id = :u"),
                         {"u": _usuario_id(personas["ana"])}).one()
    assert (fila.tipo, fila.version) == ("enviar_cv_a_ia", "v1") and fila.otorgado_en is not None


def test_repeating_a_consent_is_idempotent(cliente, personas):
    for _ in range(2):
        assert _llamar(cliente, "POST", "/consentimientos", personas["ana"], CONSENTIMIENTO).status_code == 201
    assert _filas("consentimientos", personas["ana"]) == 1


@pytest.mark.parametrize("cuerpo", [
    {"tipo": "otro", "version": "v1"},
    {"tipo": "enviar_cv_a_ia", "version": "v0"},       # S2.2: an old version is not recorded as valid
    {"tipo": "enviar_cv_a_ia"},
    {"version": "v1"},
    {"tipo": "enviar_cv_a_ia", "version": "v1", "extra": True},
    {"tipo": 7, "version": "v1"},
    [], None,
])
def test_an_invalid_consent_is_a_422_and_stores_nothing(cliente, personas, cuerpo):
    assert _llamar(cliente, "POST", "/consentimientos", personas["ana"], cuerpo).status_code == 422
    assert _filas("consentimientos", personas["ana"]) == 0


def test_S2_1_a_stored_consent_authorises_only_that_user(cliente, personas):
    _llamar(cliente, "POST", "/consentimientos", personas["ana"], CONSENTIMIENTO)
    _llamar(cliente, "GET", "/perfil", personas["bea"])  # creates Bea's user
    with base_de_datos.transaccion() as c:
        assert RepositorioDeUsuaria(c, _usuario_id(personas["ana"])).tiene_consentimiento("enviar_cv_a_ia")
        assert not RepositorioDeUsuaria(c, _usuario_id(personas["bea"])).tiene_consentimiento("enviar_cv_a_ia")


# --- S1.6: another user's data is never reachable ------------------------------------------------

def _instantanea(persona):
    with base_de_datos.transaccion() as c:
        repo = RepositorioDeUsuaria(c, _usuario_id(persona))
        return {"perfil": repo.obtener_perfil(), "consentimiento": repo.tiene_consentimiento("enviar_cv_a_ia"),
                "cvs": repo.listar_cvs(),
                "usuaria": c.execute(text("SELECT count(*) FROM usuarios WHERE id = :u"),
                                     {"u": _usuario_id(persona)}).scalar_one()}


@pytest.mark.parametrize("metodo, ruta", sorted(RUTAS_PROPIAS))
def test_S1_6_one_user_calling_an_owner_route_never_changes_another_users_data(cliente, personas, metodo, ruta):
    _llamar(cliente, "PUT", "/perfil", personas["bea"], PERFIL)
    _llamar(cliente, "POST", "/consentimientos", personas["bea"], CONSENTIMIENTO)
    with base_de_datos.transaccion() as c:  # Bea owns a stored master that nobody else may touch
        c.execute(text("INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, "
                       "caracteres) VALUES (:u, 'es', 'pdf', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)"),
                  {"u": _usuario_id(personas["bea"])})
    antes = _instantanea(personas["bea"])
    _llamar(cliente, metodo, ruta, personas["ana"], RUTAS_PROPIAS[(metodo, ruta)])
    assert _instantanea(personas["bea"]) == antes


def test_S1_6_reading_a_profile_that_is_not_yours_is_the_same_404_as_one_that_does_not_exist(cliente, personas):
    _llamar(cliente, "PUT", "/perfil", personas["bea"], PERFIL)
    con_datos_ajenos = _llamar(cliente, "GET", "/perfil", personas["ana"])
    with base_de_datos.transaccion() as c:
        c.execute(text("DELETE FROM perfil"
                       " WHERE usuario_id = :u"), {"u": _usuario_id(personas["bea"])})
    sin_datos = _llamar(cliente, "GET", "/perfil", personas["ana"])
    assert (con_datos_ajenos.status_code, con_datos_ajenos.get_json()) == (sin_datos.status_code, sin_datos.get_json())
    assert con_datos_ajenos.status_code == 404


# --- DELETE /cuenta: REQ-2.3 to REQ-2.5 -----------------------------------------------------------

TABLAS_PROPIAS = ("usuarios", "usuario_emails", "perfil", "cv_master", "consentimientos")


def _poblar(cliente, persona):
    """Profile, consent, a stored CV master and one ledger row for `persona`."""
    _llamar(cliente, "PUT", "/perfil", persona, PERFIL)
    _llamar(cliente, "POST", "/consentimientos", persona, CONSENTIMIENTO)
    with base_de_datos.transaccion() as c:
        uid = _usuario_id(persona)
        c.execute(text("INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, "
                       "caracteres) VALUES (:u, 'es', 'pdf', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)"),
                  {"u": uid})
        c.execute(text("INSERT INTO extracciones (usuario_id, modelo, estado, estimado_eur) "
                       "VALUES (:u, 'prueba-rutas', 'completada', 0.04)"), {"u": uid})


def _huerfanas():
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT count(*), coalesce(sum(estimado_eur), 0) FROM extracciones "
                              "WHERE modelo = 'prueba-rutas' AND usuario_id IS NULL")).one()


def test_S2_3_deleting_the_account_answers_204_and_removes_every_owned_row(cliente, personas):
    _poblar(cliente, personas["ana"])
    uid = _usuario_id(personas["ana"])
    r = _llamar(cliente, "DELETE", "/cuenta", personas["ana"])
    assert r.status_code == 204 and r.get_data() == b""
    with base_de_datos.transaccion() as c:
        for tabla in TABLAS_PROPIAS:
            columna = "id" if tabla == "usuarios" else "usuario_id"
            assert c.execute(text(f"SELECT count(*) FROM {tabla} WHERE {columna} = :u"), {"u": uid}).scalar_one() == 0
    cuantas, gasto = _huerfanas()
    assert cuantas == 1 and float(gasto) == 0.04  # the anonymous aggregate stays (REQ-2.4)


def test_S2_5_deleting_one_account_leaves_another_users_data_intact(cliente, personas):
    _poblar(cliente, personas["ana"])
    _poblar(cliente, personas["bea"])
    _llamar(cliente, "DELETE", "/cuenta", personas["ana"])
    assert _filas("perfil", personas["bea"]) == 1 and _filas("cv_master", personas["bea"]) == 1
    assert _filas("consentimientos", personas["bea"]) == 1
    assert _llamar(cliente, "GET", "/perfil", personas["bea"]).get_json() == PERFIL


def test_REQ_2_5_the_token_of_a_deleted_user_is_rejected_and_creates_nothing(cliente, personas):
    _poblar(cliente, personas["ana"])
    _llamar(cliente, "DELETE", "/cuenta", personas["ana"])
    for metodo, ruta in (("GET", "/perfil"), ("GET", "/yo"), ("DELETE", "/cuenta")):
        assert _llamar(cliente, metodo, ruta, personas["ana"]).status_code == 403, ruta
    with base_de_datos.transaccion() as c:
        assert c.execute(text("SELECT count(*) FROM usuarios WHERE sub = :s"), {"s": personas["ana"].sub}).scalar_one() == 0


def test_S2_7_a_re_invited_mailbox_is_a_new_user_and_the_old_spend_still_counts(cliente, personas):
    _poblar(cliente, personas["ana"])
    antiguo = _usuario_id(personas["ana"])
    _llamar(cliente, "DELETE", "/cuenta", personas["ana"])
    with base_de_datos.transaccion() as c:
        c.execute(text("UPDATE invitaciones SET usada_en = NULL, usada_por = NULL WHERE email = :e"),
                  {"e": personas["ana"].email})
    assert _llamar(cliente, "GET", "/yo", personas["ana"]).status_code == 200
    assert _usuario_id(personas["ana"]) != antiguo
    assert _filas("perfil", personas["ana"]) == 0
    with base_de_datos.transaccion() as c:
        propias = c.execute(text("SELECT count(*) FROM extracciones WHERE usuario_id = :u"),
                            {"u": _usuario_id(personas["ana"])}).scalar_one()
    assert propias == 0 and _huerfanas()[0] == 1


def test_S2_4_a_failure_during_deletion_is_a_503_and_everything_remains(cliente, personas):
    _poblar(cliente, personas["ana"])

    def cae(self):
        raise OperationalError("DELETE", {}, Exception("host secreto-db.internal refused"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(RepositorioDeUsuaria, "_eliminar_usuaria", cae)  # runs after the other tables were cleared
        r = _llamar(cliente, "DELETE", "/cuenta", personas["ana"])
    assert r.status_code == 503 and "secreto-db" not in r.get_data(as_text=True)
    for tabla in TABLAS_PROPIAS:
        assert _filas(tabla, personas["ana"]) == 1, tabla
    assert _huerfanas()[0] == 0
    assert _llamar(cliente, "GET", "/perfil", personas["ana"]).get_json() == PERFIL


def test_a_user_that_vanished_between_checks_is_the_generic_404(cliente, personas):
    _llamar(cliente, "GET", "/yo", personas["ana"])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(RepositorioDeUsuaria, "borrar_cuenta", lambda self: False)
        r = _llamar(cliente, "DELETE", "/cuenta", personas["ana"])
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "no encontrado"}


# --- failures are generic -----------------------------------------------------------------------------

def test_a_database_failure_is_a_generic_503_without_details(cliente, personas, caplog):
    def cae(self):
        raise OperationalError("SELECT", {}, Exception("host secreto-db.internal refused"))
    cliente.get("/yo", headers=personas["ana"].cabeceras)  # creates the user
    with pytest.MonkeyPatch.context() as mp, caplog.at_level(logging.INFO):
        mp.setattr(RepositorioDeUsuaria, "obtener_perfil", cae)
        r = _llamar(cliente, "GET", "/perfil", personas["ana"])
    assert r.status_code == 503 and r.get_json() == {"ok": False, "error": "servicio no disponible"}
    assert "secreto-db" not in r.get_data(as_text=True) and "secreto-db" not in caplog.text


# --- no database configured (production today) ------------------------------------------------------------

@pytest.fixture
def sin_bd(monkeypatch, par):
    def prohibido(*args, **kwargs):
        raise AssertionError("no-database mode must not touch the database")
    monkeypatch.setattr(srv, "CONFIG_OIDC", ConfiguracionOIDC(AUDIENCIA, (EMISOR,), "https://jwks",
                                                              frozenset({"ana@ejemplo.es"})))
    monkeypatch.setattr(srv, "CLAVES", ClavesPublicas("https://jwks", Descargador(_jwks(k1=par[0])), reloj=Reloj()))
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda email: None)
    monkeypatch.setattr(base_de_datos, "motor", prohibido)
    with srv.app.test_client() as c:
        yield c


@pytest.mark.parametrize("metodo, ruta", sorted(RUTAS_PROPIAS))
def test_without_a_database_owner_routes_answer_a_generic_503_never_500(sin_bd, par, metodo, ruta):
    r = sin_bd.open(ruta, method=metodo, headers=Persona("ana", par).cabeceras, json=RUTAS_PROPIAS[(metodo, ruta)])
    assert r.status_code == 503 and r.get_json() == {"ok": False, "error": "servicio no disponible"}


def test_without_a_database_yo_and_health_are_unaffected(sin_bd, par):
    assert sin_bd.get("/health").status_code == 200
    assert sin_bd.get("/yo", headers=Persona("ana", par).cabeceras).status_code == 200
