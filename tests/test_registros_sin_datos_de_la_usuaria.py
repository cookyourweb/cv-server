"""Log canary: generating a CV or a letter never writes the user's email, company or position to a log.

A legal review found `server.py` logging all three (the user's mailbox identifies her, and the
company and position say which jobs she applies to). Sentinels are planted in the request, the
generation is driven through every path that logs (success with every guardrail warning, no master,
unreadable master, Drive failures, Notion annotation) and the user's search trigger, and every record is
flattened (message, args, traceback, extras) and searched. The rule names and counts must still be
there: the fix removes the data, not the diagnostics.
"""
import logging

import pytest

import notion
import privacidad
import server as srv
from drive import MasterCV
from test_guardrails_traducido import CV_SALIDA, PERFIL_BASE, TITULAR_INVERTIDO

CLAVE = "clave-de-prueba-larga-y-aleatoria"
EMAIL = "canario.persona@example.org"
EMPRESA = "EmpresaCanarioSL"
PUESTO = "PuestoCanarioRaro"
NOMBRE = "NombreCanarioPerez"
SENTINELAS = (EMAIL, EMAIL.split("@")[0], EMPRESA, PUESTO, NOMBRE)
DATOS = {"email": EMAIL, "empresa": EMPRESA, "puesto": PUESTO, "descripcion": "corta", "idioma": "es"}
USUARIO = {"nombre": NOMBRE, "cv_master_url": "", "email": EMAIL}
CARTA = "Lideré un equipo de 45 personas con Kubernetes. Tengo ocho años con React."


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    monkeypatch.setattr(srv, "buscar_oferta_en_notion", lambda e, p: None)
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: dict(USUARIO))
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", lambda u, i: MasterCV("", ""))
    monkeypatch.setattr(srv, "call_llm_calidad", lambda p, **kw: srv.RespuestaLLM(CV_SALIDA, "modelo-falso"))
    monkeypatch.setattr(srv, "construir_titular", lambda t, m: TITULAR_INVERTIDO)
    monkeypatch.setattr(srv, "generar_docx_con_cabecera", lambda *a, **k: b"docx")
    monkeypatch.setattr(srv, "subir_cv_a_drive", lambda b, n: "https://drive/cv")
    monkeypatch.setattr(srv, "guardar_link_cv_en_notion", lambda *a, **k: True)


def _post(ruta):
    return srv.app.test_client().post(ruta, json=DATOS, headers={"X-Clave-Maquina": CLAVE}).status_code


def _con_master(monkeypatch, texto=PERFIL_BASE + "\nFrontend. React.", url="https://d/es"):
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", lambda u, i: MasterCV(texto, url))
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: {**USUARIO, "cv_master_url": url})


def _volcado(caplog):
    return privacidad.volcar_registros(caplog.records)


def _sin_sentinelas(caplog):
    volcado = _volcado(caplog)
    for sentinela in SENTINELAS:
        assert sentinela not in volcado, f"{sentinela!r} reached a log"


@pytest.mark.parametrize("ruta", ["/generar-cv", "/generar-carta"])
def test_generation_with_every_warning_logs_the_rules_but_no_user_data(ruta, monkeypatch, caplog):
    _con_master(monkeypatch)
    monkeypatch.setattr(srv, "call_llm_calidad", lambda p, **kw: srv.RespuestaLLM(
        CV_SALIDA if ruta == "/generar-cv" else CARTA, "modelo-falso"))
    with caplog.at_level(logging.DEBUG):
        assert _post(ruta) == 200
    _sin_sentinelas(caplog)
    volcado = _volcado(caplog)
    assert "CIFRAS NO RESPALDADAS" in volcado                      # the diagnostics stay
    if ruta == "/generar-cv":
        assert "TITULAR FUERA DEL CONTRATO" in volcado and "DESCRIPCION INSUFICIENTE" in volcado


@pytest.mark.parametrize("ruta", ["/generar-cv", "/generar-carta"])
def test_an_unreadable_master_logs_no_user_data(ruta, monkeypatch, caplog):
    _con_master(monkeypatch, texto="PK\x03\x04binario", url="https://d/es")
    with caplog.at_level(logging.DEBUG):
        assert _post(ruta) == 502
    _sin_sentinelas(caplog)
    assert "ILEGIBLE" in _volcado(caplog)


def test_no_master_found_logs_no_user_data(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        assert _post("/generar-cv") == 200
    _sin_sentinelas(caplog)


def test_a_master_read_logs_its_size_but_no_user_data(monkeypatch, caplog):
    _con_master(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        assert _post("/generar-cv") == 200
    _sin_sentinelas(caplog)
    assert "CV master leído" in _volcado(caplog)


@pytest.mark.parametrize("ruta", ["/generar-cv", "/generar-carta"])
def test_a_drive_read_failure_logs_the_type_not_a_message_that_may_carry_data(ruta, monkeypatch, caplog):
    def cae(u, i):
        raise RuntimeError(f"invalid_grant para {EMAIL} en {EMPRESA}/{PUESTO}")
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", cae)
    with caplog.at_level(logging.DEBUG):
        assert _post(ruta) == 502
    _sin_sentinelas(caplog)
    assert "RuntimeError" in _volcado(caplog)


def test_a_drive_upload_failure_logs_the_type_not_the_message(monkeypatch, caplog):
    def cae(b, n):
        raise RuntimeError(f"cuota de Drive de {EMAIL}: {EMPRESA} {PUESTO}")
    monkeypatch.setattr(srv, "subir_cv_a_drive", cae)
    with caplog.at_level(logging.DEBUG):
        assert _post("/generar-cv") == 500
    _sin_sentinelas(caplog)
    assert "RuntimeError" in _volcado(caplog)


# --- the Notion annotation of the generated CV -----------------------------------------------------------------

class _Resp:
    def __init__(self, estado, cuerpo=None):
        self.status_code, self._cuerpo, self.text = estado, cuerpo or {}, ""

    def json(self):
        return self._cuerpo


@pytest.mark.parametrize("consulta, parche", [
    (_Resp(200, {"results": [{"id": "pagina-1"}]}), _Resp(200)),     # annotated
    (_Resp(200, {"results": []}), None),                              # offer not found
    (_Resp(500), None),                                               # Notion error
])
def test_annotating_the_cv_in_notion_logs_no_company_or_position(consulta, parche, monkeypatch, caplog):
    monkeypatch.setattr(notion, "NOTION_DB_OFERTAS", "db-ofertas")
    monkeypatch.setattr(notion.requests, "post", lambda *a, **k: consulta)
    monkeypatch.setattr(notion.requests, "patch", lambda *a, **k: parche)
    with caplog.at_level(logging.DEBUG):
        notion.guardar_link_cv_en_notion(EMPRESA, PUESTO, "https://drive/cv", "cv.docx")
    _sin_sentinelas(caplog)
    assert caplog.records, "the path under test should log something"


# --- the search trigger (Notion users) -----------------------------------------------------------------------------

class _Webhook:
    def __init__(self, estado, texto=""):
        self.status_code, self.text = estado, texto


@pytest.mark.parametrize("respuesta", [_Webhook(200), _Webhook(500, "No item to return was found")])
def test_triggering_the_search_logs_no_email(respuesta, monkeypatch, caplog):
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: respuesta)
    with caplog.at_level(logging.DEBUG):
        assert srv.disparar_busqueda(dict(USUARIO)).disparada is True
    _sin_sentinelas(caplog)
    assert caplog.records


# --- the opaque label ------------------------------------------------------------------------------------------------------

def test_the_opaque_label_is_stable_within_a_process_and_hides_the_value():
    etiqueta = privacidad.etiqueta_opaca(EMAIL)
    assert etiqueta == privacidad.etiqueta_opaca(EMAIL.upper() + " ")      # same mailbox, same label
    assert etiqueta != privacidad.etiqueta_opaca("otra@example.org")
    assert EMAIL not in etiqueta and "canario" not in etiqueta and len(etiqueta) <= 16
