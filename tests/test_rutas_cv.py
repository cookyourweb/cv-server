"""POST /cv, GET /cv, DELETE /cv/{idioma}: the encrypted CV master (spec S3.1, S3.2, S3.10).

Wire format taken from the panel (panel-empleo extractor-de-cv-http.ts): multipart field
`archivo`; 413 size, 415 type, 422 unreadable, 403 no consent. Runs against a real
PostgreSQL (DATABASE_URL_PRUEBAS) with real signed tokens and cleans up after itself.
"""
import base64
import io
import os

import pytest
from fabrica_de_cvs import CV_EN, CV_ES, docx_con_parrafos, pdf_con_texto, pdf_escaneado
from sqlalchemy import text
from test_rutas_alta import _llamar, _usuario_id, bd, cliente, migrado, par, personas  # noqa: F401

import base_de_datos
import cifrado
import lectura_cv
import server as srv

CONSENTIMIENTO_CV = {"tipo": "almacenar_cv", "version": "v1"}


@pytest.fixture(autouse=True)
def claves(monkeypatch):
    monkeypatch.setenv("CV_CLAVES", "1:" + base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "1")


def _subir(cliente, persona, datos, nombre="cv.pdf", tipo="application/pdf", campo="archivo"):
    return cliente.post("/cv", headers=persona.cabeceras, data={campo: (io.BytesIO(datos), nombre, tipo)})


def _consentir(cliente, persona, consentimiento=CONSENTIMIENTO_CV):
    assert _llamar(cliente, "POST", "/consentimientos", persona, consentimiento).status_code == 201


def _filas_cv(persona):
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT idioma, formato, clave_version, nonce, cifrado, caracteres FROM cv_master "
                              "WHERE usuario_id = :u ORDER BY idioma"), {"u": _usuario_id(persona)}).all()


def _texto_guardado(persona, fila):
    return cifrado.descifrar(fila.clave_version, bytes(fila.nonce), bytes(fila.cifrado),
                             _usuario_id(persona), fila.idioma)


# --- S3.1 / S3.2: stored encrypted ---------------------------------------------------------------

@pytest.mark.parametrize("datos, nombre, tipo, formato", [
    (pdf_con_texto(CV_ES), "cv.pdf", "application/pdf", "pdf"),
    (docx_con_parrafos(CV_ES), "cv.docx",
     "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
])
def test_S3_1_S3_2_a_valid_cv_is_stored_encrypted_and_answers_201(cliente, personas, datos, nombre, tipo, formato):
    _consentir(cliente, personas["ana"])
    r = _subir(cliente, personas["ana"], datos, nombre, tipo)
    (fila,) = _filas_cv(personas["ana"])
    assert r.status_code == 201
    assert r.get_json() == {"idioma": "es", "formato": formato, "caracteres": fila.caracteres}
    # A raw SQL read shows no plaintext sentence and no raw file; only the key owner can read it back.
    guardado = bytes(fila.cifrado)
    assert "Desarrolladora frontend".encode() not in guardado and b"Angular" not in guardado
    assert b"%PDF-" not in guardado and b"PK\x03\x04" not in guardado and len(bytes(fila.nonce)) == 12
    assert "Desarrolladora frontend" in _texto_guardado(personas["ana"], fila)
    assert len(_texto_guardado(personas["ana"], fila)) == fila.caracteres


def test_the_row_is_bound_to_its_owner_and_language(cliente, personas):
    _consentir(cliente, personas["ana"])
    _subir(cliente, personas["ana"], pdf_con_texto(CV_ES))
    (fila,) = _filas_cv(personas["ana"])
    with pytest.raises(cifrado.ErrorDeCifrado):  # the AAD names the owner: another id does not decrypt it
        cifrado.descifrar(fila.clave_version, bytes(fila.nonce), bytes(fila.cifrado), "otra-usuaria", "es")


def test_the_language_is_detected_and_each_language_has_its_own_master(cliente, personas):
    _consentir(cliente, personas["ana"])
    assert _subir(cliente, personas["ana"], pdf_con_texto(CV_ES)).get_json()["idioma"] == "es"
    assert _subir(cliente, personas["ana"], pdf_con_texto(CV_EN)).get_json()["idioma"] == "en"
    assert [f.idioma for f in _filas_cv(personas["ana"])] == ["en", "es"]


# --- S3.10: replace ----------------------------------------------------------------------------------

def test_S3_10_a_second_upload_in_the_same_language_replaces_the_master(cliente, personas):
    _consentir(cliente, personas["ana"])
    _subir(cliente, personas["ana"], pdf_con_texto(CV_ES))
    nuevo = ["Segunda versión del currículum con experiencia en Angular y trabajo en equipo."] * 6
    assert _subir(cliente, personas["ana"], docx_con_parrafos(nuevo)).status_code == 201
    (fila,) = _filas_cv(personas["ana"])
    assert fila.formato == "docx" and "Segunda versión" in _texto_guardado(personas["ana"], fila)


# --- consent -----------------------------------------------------------------------------------------------

def test_without_the_stored_consent_the_upload_is_a_403_and_nothing_is_read_or_stored(cliente, personas, monkeypatch):
    def prohibido(datos):
        raise AssertionError("the file must not be parsed without consent")
    monkeypatch.setattr(lectura_cv, "leer_cv", prohibido)
    monkeypatch.setattr(srv.rutas_alta, "leer_cv", prohibido)
    r = _subir(cliente, personas["ana"], pdf_con_texto(CV_ES))
    assert r.status_code == 403 and r.get_json()["ok"] is False
    assert _filas_cv(personas["ana"]) == []


def test_the_consent_to_send_the_cv_to_an_ai_does_not_authorise_storing_it(cliente, personas):
    _consentir(cliente, personas["ana"], {"tipo": "enviar_cv_a_ia", "version": "v1"})
    assert _subir(cliente, personas["ana"], pdf_con_texto(CV_ES)).status_code == 403


def test_an_old_consent_version_does_not_authorise_the_upload(cliente, personas):
    cliente.get("/yo", headers=personas["ana"].cabeceras)  # creates the user
    with base_de_datos.transaccion() as c:
        c.execute(text("INSERT INTO consentimientos (usuario_id, tipo, version) VALUES (:u, 'almacenar_cv', 'v0')"),
                  {"u": _usuario_id(personas["ana"])})
    assert _subir(cliente, personas["ana"], pdf_con_texto(CV_ES)).status_code == 403


def test_a_revoked_consent_does_not_authorise_the_upload(cliente, personas):
    _consentir(cliente, personas["ana"])
    with base_de_datos.transaccion() as c:
        c.execute(text("UPDATE consentimientos SET revocado_en = now() WHERE usuario_id = :u"),
                  {"u": _usuario_id(personas["ana"])})
    assert _subir(cliente, personas["ana"], pdf_con_texto(CV_ES)).status_code == 403


# --- rejections: panel contract 413 / 415 / 422 -----------------------------------------------------------------

def test_the_request_size_is_capped_by_flask_at_3_mb():
    assert srv.app.config["MAX_CONTENT_LENGTH"] == 3 * 1024 * 1024


def test_S3_3_a_file_over_the_cv_limit_is_a_413_and_is_not_parsed(cliente, personas, monkeypatch):
    _consentir(cliente, personas["ana"])

    def prohibido(*args, **kwargs):
        raise AssertionError("an oversize file must not be parsed")
    monkeypatch.setattr(lectura_cv, "_extraer_pdf", prohibido)
    r = _subir(cliente, personas["ana"], b"%PDF-" + b"0" * lectura_cv.LIMITE_BYTES)
    assert r.status_code == 413 and r.get_json() == {"ok": False, "error": "archivo demasiado grande", "motivo": "tamano"}
    assert _filas_cv(personas["ana"]) == []


def test_a_request_over_3_mb_fails_early_as_a_json_413(cliente, personas, monkeypatch):
    _consentir(cliente, personas["ana"])
    monkeypatch.setattr(lectura_cv, "leer_cv", lambda d: pytest.fail("parsed"))
    r = _subir(cliente, personas["ana"], b"%PDF-" + b"0" * (3 * 1024 * 1024))
    assert r.status_code == 413 and r.get_json()["ok"] is False
    assert _filas_cv(personas["ana"]) == []


@pytest.mark.parametrize("datos, nombre, tipo", [
    (b"<html><body>hola</body></html>" * 20, "cv.pdf", "application/pdf"),                    # S3.4: renamed HTML
    (b"MZ\x90\x00" + b"\x00" * 600, "cv.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    (b"", "cv.pdf", "application/pdf"),
])
def test_S3_4_the_real_type_decides_not_the_name_or_content_type(cliente, personas, datos, nombre, tipo):
    _consentir(cliente, personas["ana"])
    r = _subir(cliente, personas["ana"], datos, nombre, tipo)
    assert r.status_code == 415 and r.get_json()["motivo"] == "tipo"
    assert _filas_cv(personas["ana"]) == []


@pytest.mark.parametrize("datos, motivo", [
    (b"%PDF-1.4\nbroken", "ilegible"),
    (pdf_escaneado(), "sin_texto"),                      # S3.8: scanned, use the manual form
    (pdf_con_texto(CV_ES, paginas=11), "largo"),
    (docx_con_parrafos(["corto"]), "sin_texto"),
])
def test_unreadable_or_empty_cvs_are_a_422_with_a_reason_and_store_nothing(cliente, personas, datos, motivo):
    _consentir(cliente, personas["ana"])
    r = _subir(cliente, personas["ana"], datos)
    assert r.status_code == 422 and r.get_json()["motivo"] == motivo and r.get_json()["ok"] is False
    assert _filas_cv(personas["ana"]) == []


@pytest.mark.parametrize("enviar", [
    lambda c, p: c.post("/cv", headers=p.cabeceras),
    lambda c, p: c.post("/cv", headers=p.cabeceras, data={"otro": (io.BytesIO(b"x"), "a.pdf")}),
    lambda c, p: c.post("/cv", headers=p.cabeceras, json={"archivo": "x"}),
])
def test_a_request_without_the_archivo_field_is_a_422(cliente, personas, enviar):
    _consentir(cliente, personas["ana"])
    assert enviar(cliente, personas["ana"]).status_code == 422


def test_without_a_keyring_the_upload_is_a_generic_503_and_stores_nothing(cliente, personas, monkeypatch):
    _consentir(cliente, personas["ana"])
    monkeypatch.delenv("CV_CLAVES")
    r = _subir(cliente, personas["ana"], pdf_con_texto(CV_ES))
    assert r.status_code == 503 and r.get_json() == {"ok": False, "error": "servicio no disponible"}
    assert _filas_cv(personas["ana"]) == []


# --- GET /cv and DELETE /cv/{idioma} ------------------------------------------------------------------------------------

def test_listing_shows_metadata_only_never_content(cliente, personas):
    assert _llamar(cliente, "GET", "/cv", personas["ana"]).get_json() == []
    _consentir(cliente, personas["ana"])
    _subir(cliente, personas["ana"], pdf_con_texto(CV_ES))
    _subir(cliente, personas["ana"], docx_con_parrafos(CV_EN))
    r = _llamar(cliente, "GET", "/cv", personas["ana"])
    assert r.status_code == 200
    assert [(x["idioma"], x["formato"]) for x in r.get_json()] == [("en", "docx"), ("es", "pdf")]
    assert all(set(x) == {"idioma", "formato", "subido_en"} for x in r.get_json())
    assert "Angular" not in r.get_data(as_text=True)


def test_deleting_a_master_is_a_204_then_a_404(cliente, personas):
    _consentir(cliente, personas["ana"])
    _subir(cliente, personas["ana"], pdf_con_texto(CV_ES))
    _subir(cliente, personas["ana"], pdf_con_texto(CV_EN))
    assert _llamar(cliente, "DELETE", "/cv/es", personas["ana"]).status_code == 204
    assert [f.idioma for f in _filas_cv(personas["ana"])] == ["en"]
    r = _llamar(cliente, "DELETE", "/cv/es", personas["ana"])
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "no encontrado"}


@pytest.mark.parametrize("idioma", ["fr", "ES", "xx", "es%20"])
def test_an_unknown_language_is_the_same_404(cliente, personas, idioma):
    r = _llamar(cliente, "DELETE", f"/cv/{idioma}", personas["ana"])
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "no encontrado"}


def test_S1_6_users_only_see_and_delete_their_own_masters(cliente, personas):
    for nombre in ("ana", "bea"):
        _consentir(cliente, personas[nombre])
        _subir(cliente, personas[nombre], pdf_con_texto(CV_ES))
    antes = [(f.idioma, bytes(f.cifrado)) for f in _filas_cv(personas["bea"])]
    # Ana deletes "es": that is HER es master, Bea's is untouched.
    assert _llamar(cliente, "DELETE", "/cv/es", personas["ana"]).status_code == 204
    assert _llamar(cliente, "DELETE", "/cv/es", personas["ana"]).status_code == 404
    assert [(f.idioma, bytes(f.cifrado)) for f in _filas_cv(personas["bea"])] == antes
    assert len(_llamar(cliente, "GET", "/cv", personas["bea"]).get_json()) == 1
    assert _llamar(cliente, "GET", "/cv", personas["ana"]).get_json() == []


def test_deleting_the_account_removes_the_masters(cliente, personas):
    _consentir(cliente, personas["ana"])
    _subir(cliente, personas["ana"], pdf_con_texto(CV_ES))
    uid = _usuario_id(personas["ana"])
    assert _llamar(cliente, "DELETE", "/cuenta", personas["ana"]).status_code == 204
    with base_de_datos.transaccion() as c:
        assert c.execute(text("SELECT count(*) FROM cv_master WHERE usuario_id = :u"), {"u": uid}).scalar_one() == 0
