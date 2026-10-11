"""Consent version v2: a consent given under the v1 text no longer authorises anything.

v1 said the CV was sent "once" to extract the profile; the generation of every CV and letter
also uses it, so the text changed in substance and users must accept again. `/yo` tells the
panel which consents are current, so a user who already has a profile is sent back to the
consent step (the panel cannot infer it from `tiene_perfil`). Real PostgreSQL, real tokens.
"""
import base64
import io
import os

import pytest
from fabrica_de_cvs import CV_ES, pdf_con_texto
from sqlalchemy import text
from test_rutas_alta import _llamar, _usuario_id, bd, cliente, migrado, par, personas  # noqa: F401

import base_de_datos
import cifrado
import fuente_master
from repositorio import VERSION_DE_CONSENTIMIENTO, RepositorioDeUsuaria

pytestmark = pytest.mark.bd


@pytest.fixture(autouse=True)
def claves(monkeypatch):
    monkeypatch.setenv("CV_CLAVES", "1:" + base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "1")


def _dar_v1(persona, *tipos):
    """Consents as they were stored before the bump."""
    with base_de_datos.transaccion() as c:
        for tipo in tipos:
            c.execute(text("INSERT INTO consentimientos (usuario_id, tipo, version) VALUES (:u, :t, 'v1')"),
                      {"u": _usuario_id(persona), "t": tipo})


def test_the_current_version_is_v2():
    assert VERSION_DE_CONSENTIMIENTO == "v2"


def test_the_server_refuses_to_record_a_v1_consent_and_accepts_v2(cliente, personas):
    v1 = _llamar(cliente, "POST", "/consentimientos", personas["ana"], {"tipo": "enviar_cv_a_ia", "version": "v1"})
    assert v1.status_code == 422
    v2 = _llamar(cliente, "POST", "/consentimientos", personas["ana"], {"tipo": "enviar_cv_a_ia", "version": "v2"})
    assert v2.status_code == 201


def test_a_v1_consent_does_not_count_for_either_type(cliente, personas):
    _llamar(cliente, "GET", "/yo", personas["ana"])
    _dar_v1(personas["ana"], "almacenar_cv", "enviar_cv_a_ia")
    with base_de_datos.transaccion() as c:
        repo = RepositorioDeUsuaria(c, _usuario_id(personas["ana"]))
        assert not repo.tiene_consentimiento("almacenar_cv") and not repo.tiene_consentimiento("enviar_cv_a_ia")


def test_a_v1_consent_stops_the_neon_master_the_extraction_and_the_upload(cliente, personas):
    _llamar(cliente, "GET", "/yo", personas["ana"])
    uid = _usuario_id(personas["ana"])
    with base_de_datos.transaccion() as c:
        version, nonce, cif = cifrado.cifrar("Frontend senior con Angular", uid, "es")
        RepositorioDeUsuaria(c, uid).guardar_cv("es", "pdf", version, nonce, cif, 27)
    _dar_v1(personas["ana"], "almacenar_cv", "enviar_cv_a_ia")
    assert fuente_master.MasterEnBase(fuente_master._RepoEfimero(uid)).leer("es").texto == ""
    assert _llamar(cliente, "POST", "/extraccion", personas["ana"]).status_code == 403
    subida = cliente.post("/cv", headers=personas["ana"].cabeceras,
                          data={"archivo": (io.BytesIO(pdf_con_texto(CV_ES)), "cv.pdf", "application/pdf")})
    assert subida.status_code == 403


def test_yo_reports_which_consents_are_current_so_the_panel_can_ask_again(cliente, personas):
    assert _llamar(cliente, "GET", "/yo", personas["ana"]).get_json()["consentimientos"] == {
        "almacenar_cv": False, "enviar_cv_a_ia": False}
    _dar_v1(personas["ana"], "almacenar_cv", "enviar_cv_a_ia")
    assert _llamar(cliente, "GET", "/yo", personas["ana"]).get_json()["consentimientos"] == {
        "almacenar_cv": False, "enviar_cv_a_ia": False}
    _llamar(cliente, "POST", "/consentimientos", personas["ana"], {"tipo": "almacenar_cv", "version": "v2"})
    assert _llamar(cliente, "GET", "/yo", personas["ana"]).get_json()["consentimientos"] == {
        "almacenar_cv": True, "enviar_cv_a_ia": False}


def test_yo_omits_the_field_without_a_database(cliente, personas, monkeypatch):
    from test_rutas_alta import srv
    monkeypatch.setattr(srv.usuarias, "consentimientos_vigentes",
                        lambda *a, **k: (_ for _ in ()).throw(srv.usuarias.BaseDeDatosNoDisponible()))
    cuerpo = _llamar(cliente, "GET", "/yo", personas["ana"]).get_json()
    assert "consentimientos" not in cuerpo
