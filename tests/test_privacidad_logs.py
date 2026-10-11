"""S3.9: CV content never reaches a log at any level, on any path (REQ-3.5).

A sentinel is planted in the file CONTENT and in the file NAME, then the upload is driven
through every outcome: success, each rejection, missing consent, missing keyring and a
database failure whose driver message also carries the sentinel. Every log record is
flattened (message, args, traceback, extras) and searched, and so is every response body.
"""
import base64
import io
import logging
import os

import pytest
from fabrica_de_cvs import CV_ES, docx_con_parrafos, pdf_con_texto, pdf_escaneado
from sqlalchemy.exc import OperationalError
from test_rutas_alta import _llamar, bd, cliente, migrado, par, personas  # noqa: F401

import lectura_cv
import privacidad
from repositorio import RepositorioDeUsuaria

CENTINELA = "CENTINELA-CV-PRIVADO-90210"
NOMBRE = f"{CENTINELA}.pdf"


@pytest.fixture(autouse=True)
def claves(monkeypatch):
    monkeypatch.setenv("CV_CLAVES", "1:" + base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "1")


def _subir(cliente, persona, datos):
    return cliente.post("/cv", headers=persona.cabeceras,
                        data={"archivo": (io.BytesIO(datos), NOMBRE, "application/pdf")})


def _conceder(cliente, persona):
    _llamar(cliente, "POST", "/consentimientos", persona, {"tipo": "almacenar_cv", "version": "v1"})


CON_CENTINELA = pdf_con_texto(CV_ES + [CENTINELA])

CAMINOS = {
    "stored": lambda c, p: _subir(c, p, CON_CENTINELA),
    "oversize": lambda c, p: _subir(c, p, b"%PDF-" + CENTINELA.encode() * (lectura_cv.LIMITE_BYTES // 20)),
    "request over the cap": lambda c, p: _subir(c, p, b"%PDF-" + CENTINELA.encode() + b"0" * (3 * 1024 * 1024)),
    "wrong type": lambda c, p: _subir(c, p, b"<html>" + CENTINELA.encode() + b"</html>" * 50),
    "corrupt pdf": lambda c, p: _subir(c, p, b"%PDF-1.4\n" + CENTINELA.encode() + b"\n%%EOF"),
    "truncated pdf": lambda c, p: _subir(c, p, CON_CENTINELA[:-150]),
    "corrupt docx": lambda c, p: _subir(c, p, b"PK\x03\x04" + CENTINELA.encode() * 5),
    "scanned": lambda c, p: _subir(c, p, pdf_escaneado()),
    "too short": lambda c, p: _subir(c, p, docx_con_parrafos([CENTINELA])),
    "no archivo": lambda c, p: c.post("/cv", headers=p.cabeceras, data={CENTINELA: CENTINELA}),
    "listing": lambda c, p: c.get("/cv", headers=p.cabeceras),
    "deleting": lambda c, p: c.delete("/cv/es", headers=p.cabeceras),
}


@pytest.mark.parametrize("camino", sorted(CAMINOS))
def test_S3_9_the_sentinel_never_reaches_a_log_or_a_response(cliente, personas, caplog, camino):
    _conceder(cliente, personas["ana"])
    with caplog.at_level(logging.DEBUG):
        respuesta = CAMINOS[camino](cliente, personas["ana"])
    assert respuesta.status_code in {200, 201, 204, 404, 413, 415, 422}
    assert CENTINELA not in privacidad.volcar_registros(caplog.records)
    assert CENTINELA not in respuesta.get_data(as_text=True) + str(respuesta.headers)


def test_S3_9_without_consent_nothing_is_logged_either(cliente, personas, caplog):
    with caplog.at_level(logging.DEBUG):
        r = _subir(cliente, personas["ana"], CON_CENTINELA)
    assert r.status_code == 403 and CENTINELA not in privacidad.volcar_registros(caplog.records)


def test_S3_9_a_missing_keyring_is_logged_by_type_only(cliente, personas, caplog, monkeypatch):
    _conceder(cliente, personas["ana"])
    monkeypatch.delenv("CV_CLAVES")
    with caplog.at_level(logging.DEBUG):
        r = _subir(cliente, personas["ana"], CON_CENTINELA)
    volcado = privacidad.volcar_registros(caplog.records)
    assert r.status_code == 503 and CENTINELA not in volcado and "ErrorDeCifrado" in volcado


def test_S3_9_a_database_failure_while_storing_never_logs_its_message_or_the_cv(cliente, personas, caplog):
    _conceder(cliente, personas["ana"])

    def cae(self, *args, **kwargs):
        raise OperationalError("INSERT", {}, Exception(f"driver says {CENTINELA}"))
    with pytest.MonkeyPatch.context() as mp, caplog.at_level(logging.DEBUG):
        mp.setattr(RepositorioDeUsuaria, "guardar_cv", cae)
        r = _subir(cliente, personas["ana"], CON_CENTINELA)
    assert r.status_code == 503
    assert CENTINELA not in privacidad.volcar_registros(caplog.records) + r.get_data(as_text=True)


# --- the canary itself must be able to see a leak -----------------------------------------------------------------

@pytest.mark.parametrize("registrar", [
    lambda log: log.info("plain %s", CENTINELA),
    lambda log: log.info("fixed message", extra={"datos": CENTINELA}),
    lambda log: log.info("args %s", (CENTINELA,)),
    lambda log: _con_excepcion(log),
    lambda log: log.info(CENTINELA),
])
def test_the_canary_helper_detects_a_leak(caplog, registrar):
    log = logging.getLogger("prueba.canario")
    with caplog.at_level(logging.DEBUG):
        registrar(log)
    assert CENTINELA in privacidad.volcar_registros(caplog.records)


def _con_excepcion(log):
    try:
        raise ValueError(CENTINELA)
    except ValueError:
        log.exception("failed")


def test_registrar_fallo_logs_the_type_and_never_the_message(caplog):
    log = logging.getLogger("prueba.fallo")
    with caplog.at_level(logging.DEBUG):
        privacidad.registrar_fallo(log, "reading failed", ValueError(CENTINELA))
    volcado = privacidad.volcar_registros(caplog.records)
    assert "ValueError" in volcado and "reading failed" in volcado and CENTINELA not in volcado
