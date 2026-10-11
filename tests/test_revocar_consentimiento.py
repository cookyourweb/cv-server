"""DELETE /consentimientos/{tipo}: withdrawing a consent (the text promises "whenever you want").

Contract the panel implements against: 204 with no body (also when it was already revoked or
never given), 422 {ok:false, error, campos:["tipo"]} for an unknown type. Revoking
`enviar_cv_a_ia` stops the extraction and the Neon master reaching any model; revoking
`almacenar_cv` also deletes every stored CV in the same transaction and blocks new uploads until
the consent is given again. Real PostgreSQL (DATABASE_URL_PRUEBAS), real signed tokens.
"""
import base64
import io
import os

import pytest
from fabrica_de_cvs import CV_ES, pdf_con_texto
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_rutas_alta import _filas, _llamar, _usuario_id, bd, cliente, migrado, par, personas  # noqa: F401

import base_de_datos
import cifrado
import fuente_master
from repositorio import VERSION_DE_CONSENTIMIENTO, RepositorioDeUsuaria

pytestmark = pytest.mark.bd

IA = {"tipo": "enviar_cv_a_ia", "version": VERSION_DE_CONSENTIMIENTO}
ALMACENAR = {"tipo": "almacenar_cv", "version": VERSION_DE_CONSENTIMIENTO}


@pytest.fixture(autouse=True)
def claves(monkeypatch):
    monkeypatch.setenv("CV_CLAVES", "1:" + base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "1")


def _consentir(cliente, persona, *consentimientos):
    for c in consentimientos:
        assert _llamar(cliente, "POST", "/consentimientos", persona, c).status_code == 201


def _revocar(cliente, persona, tipo):
    return _llamar(cliente, "DELETE", f"/consentimientos/{tipo}", persona)


def _subir(cliente, persona):
    return cliente.post("/cv", headers=persona.cabeceras,
                        data={"archivo": (io.BytesIO(pdf_con_texto(CV_ES)), "cv.pdf", "application/pdf")})


def _estado(persona, tipo):
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT revocado_en FROM consentimientos WHERE usuario_id = :u AND tipo = :t"),
                         {"u": _usuario_id(persona), "t": tipo}).all()


@pytest.mark.parametrize("tipo", ["almacenar_cv", "enviar_cv_a_ia"])
def test_revoking_an_active_consent_answers_204_and_stamps_revocado_en(cliente, personas, tipo):
    _consentir(cliente, personas["ana"], IA, ALMACENAR)
    r = _revocar(cliente, personas["ana"], tipo)
    assert r.status_code == 204 and r.get_data() == b""
    ((revocado,),) = _estado(personas["ana"], tipo)
    assert revocado is not None
    with base_de_datos.transaccion() as c:
        assert not RepositorioDeUsuaria(c, _usuario_id(personas["ana"])).tiene_consentimiento(tipo)


def test_revoking_leaves_the_other_consent_alone(cliente, personas):
    _consentir(cliente, personas["ana"], IA, ALMACENAR)
    _revocar(cliente, personas["ana"], "enviar_cv_a_ia")
    with base_de_datos.transaccion() as c:
        assert RepositorioDeUsuaria(c, _usuario_id(personas["ana"])).tiene_consentimiento("almacenar_cv")


@pytest.mark.parametrize("tipo", ["almacenar_cv", "enviar_cv_a_ia"])
def test_revoking_is_idempotent_also_when_it_was_never_given(cliente, personas, tipo):
    assert _revocar(cliente, personas["ana"], tipo).status_code == 204          # never given
    _consentir(cliente, personas["ana"], {"tipo": tipo, "version": VERSION_DE_CONSENTIMIENTO})
    assert _revocar(cliente, personas["ana"], tipo).status_code == 204
    ((primera,),) = _estado(personas["ana"], tipo)
    assert _revocar(cliente, personas["ana"], tipo).status_code == 204          # already revoked
    assert _estado(personas["ana"], tipo) == [(primera,)]                        # the first stamp is kept


@pytest.mark.parametrize("tipo", ["otro", "ALMACENAR_CV", "cv", "0"])
def test_an_unknown_type_is_a_422_naming_the_field(cliente, personas, tipo):
    r = _revocar(cliente, personas["ana"], tipo)
    assert r.status_code == 422
    assert r.get_json() == {"ok": False, "error": "datos no validos", "campos": ["tipo"]}


def test_revoking_does_not_touch_another_users_consent(cliente, personas):
    _consentir(cliente, personas["bea"], IA)
    _llamar(cliente, "GET", "/yo", personas["ana"])
    _revocar(cliente, personas["ana"], "enviar_cv_a_ia")
    with base_de_datos.transaccion() as c:
        assert RepositorioDeUsuaria(c, _usuario_id(personas["bea"])).tiene_consentimiento("enviar_cv_a_ia")


def test_revoking_the_ai_consent_stops_the_extraction_with_a_403(cliente, personas):
    _consentir(cliente, personas["ana"], IA, ALMACENAR)
    assert _subir(cliente, personas["ana"]).status_code == 201
    _revocar(cliente, personas["ana"], "enviar_cv_a_ia")
    r = _llamar(cliente, "POST", "/extraccion", personas["ana"])
    assert r.status_code == 403 and r.get_json() == {"ok": False, "error": "consentimiento necesario"}


def test_revoking_the_ai_consent_stops_the_neon_master_reaching_a_model(cliente, personas):
    _consentir(cliente, personas["ana"], IA, ALMACENAR)
    assert _subir(cliente, personas["ana"]).status_code == 201
    uid = _usuario_id(personas["ana"])
    fuente = fuente_master.MasterEnBase(fuente_master._RepoEfimero(uid))
    assert fuente.leer("es").texto != ""
    _revocar(cliente, personas["ana"], "enviar_cv_a_ia")
    assert fuente.leer("es").texto == ""
    assert _filas("cv_master", personas["ana"]) == 1                              # the CV itself stays stored


def test_revoking_the_storage_consent_deletes_every_cv_and_blocks_new_uploads(cliente, personas):
    _consentir(cliente, personas["ana"], IA, ALMACENAR)
    assert _subir(cliente, personas["ana"]).status_code == 201
    with base_de_datos.transaccion() as c:                                        # a second language
        c.execute(text("INSERT INTO cv_master (usuario_id, idioma, formato, clave_version, nonce, cifrado, "
                       "caracteres) VALUES (:u, 'en', 'pdf', 1, decode(repeat('00', 12), 'hex'), '\\x01', 10)"),
                  {"u": _usuario_id(personas["ana"])})
    assert _filas("cv_master", personas["ana"]) == 2
    assert _revocar(cliente, personas["ana"], "almacenar_cv").status_code == 204
    assert _filas("cv_master", personas["ana"]) == 0
    assert _subir(cliente, personas["ana"]).status_code == 403
    assert _filas("cv_master", personas["ana"]) == 0


def test_revoking_the_storage_consent_never_deletes_another_users_cvs(cliente, personas):
    for nombre in ("ana", "bea"):
        _consentir(cliente, personas[nombre], ALMACENAR)
        assert _subir(cliente, personas[nombre]).status_code == 201
    _revocar(cliente, personas["ana"], "almacenar_cv")
    assert _filas("cv_master", personas["ana"]) == 0 and _filas("cv_master", personas["bea"]) == 1


def test_revoking_the_storage_consent_is_atomic_with_the_deletion_of_the_cvs(cliente, personas):
    _consentir(cliente, personas["ana"], ALMACENAR)
    assert _subir(cliente, personas["ana"]).status_code == 201

    def cae(self, *a, **k):
        raise OperationalError("DELETE", {}, Exception("host secreto-db.internal refused"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(RepositorioDeUsuaria, "borrar_todos_los_cvs", cae)
        r = _revocar(cliente, personas["ana"], "almacenar_cv")
    assert r.status_code == 503 and "secreto-db" not in r.get_data(as_text=True)
    ((revocado,),) = _estado(personas["ana"], "almacenar_cv")
    assert revocado is None and _filas("cv_master", personas["ana"]) == 1          # nothing half-done


@pytest.mark.parametrize("tipo, otro", [("almacenar_cv", ALMACENAR), ("enviar_cv_a_ia", IA)])
def test_giving_the_consent_again_after_revoking_it_authorises_again(cliente, personas, tipo, otro):
    _consentir(cliente, personas["ana"], otro)
    _revocar(cliente, personas["ana"], tipo)
    _consentir(cliente, personas["ana"], otro)
    assert _filas("consentimientos", personas["ana"]) == 1
    with base_de_datos.transaccion() as c:
        assert RepositorioDeUsuaria(c, _usuario_id(personas["ana"])).tiene_consentimiento(tipo)
    if tipo == "almacenar_cv":
        assert _subir(cliente, personas["ana"]).status_code == 201


def test_revoking_needs_a_token(cliente):
    assert cliente.delete("/consentimientos/enviar_cv_a_ia").status_code == 401
