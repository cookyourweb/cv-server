"""/generar-carta resolves the master through fuente_master (Drive, Neon or both).

Notion, Drive and the LLM are replaced; nothing leaves the process. The legacy case (no
DATABASE_URL, master in Drive) must behave exactly as before.
"""
import pytest

import fuente_master as fm
import server as srv
from drive import MasterCV

CLAVE = "clave-de-prueba-larga-y-aleatoria"
DATOS = {"email": "vero@example.com", "empresa": "ACME", "puesto": "Frontend", "descripcion": "Angular " * 40,
         "idioma": "es"}


@pytest.fixture
def entorno(monkeypatch):
    prompts = []

    def llm(prompt, **kw):
        prompts.append(prompt)
        return srv.RespuestaLLM("Estimados/as, soy frontend con Angular.", "modelo-falso")

    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    monkeypatch.setattr(srv, "buscar_oferta_en_notion", lambda e, p: None)
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: {"nombre": "Vero", "cv_master_url": ""})
    monkeypatch.setattr(srv, "call_llm_calidad", llm)
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", lambda u, i: MasterCV("", ""))
    return prompts


def _carta():
    r = srv.app.test_client().post("/generar-carta", json=DATOS, headers={"X-Clave-Maquina": CLAVE})
    return r.status_code, r.get_json()


def test_legacy_flow_reads_the_master_from_drive_as_before(entorno, monkeypatch):
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", lambda u, i: MasterCV("Master de Drive ES", "https://d/es"))
    status, cuerpo = _carta()
    assert status == 200 and cuerpo["cv_master_usado"] is True and cuerpo["master_traducido"] is False
    assert "Master de Drive ES" in entorno[0]


def test_a_drive_failure_keeps_answering_502(entorno, monkeypatch):
    def roto(u, i):
        raise RuntimeError("token caducado")
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", roto)
    status, cuerpo = _carta()
    assert status == 502 and "token caducado" in cuerpo["error"]


def test_a_neon_master_in_the_other_language_is_used_and_flagged(entorno, monkeypatch):
    class Base:
        def leer(self, idioma):
            return fm.LecturaMaster("Master de Neon EN" if idioma == "en" else "", "", idioma)
    monkeypatch.setattr(fm, "base_para_email", lambda email: Base())
    status, cuerpo = _carta()
    assert status == 200 and cuerpo["master_traducido"] is True and cuerpo["cv_master_usado"] is True
    assert "Master de Neon EN" in entorno[0]


def _base_con(consentimiento):
    version_texto = "Master de Neon ES secreto"

    class Repo:
        usuario_id = "u-1"

        def tiene_consentimiento(self, tipo):
            return consentimiento

        def obtener_cv(self, idioma):
            import cifrado
            v, n, c = cifrado.cifrar(version_texto, "u-1", idioma)
            return type("F", (), {"clave_version": v, "nonce": n, "cifrado": c})()
    return fm.MasterEnBase(Repo()), version_texto


def _con_claves(monkeypatch):
    import base64
    import os
    monkeypatch.setenv("CV_CLAVES", "1:" + base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "1")


def test_a_neon_master_without_ai_consent_never_reaches_the_prompt(entorno, monkeypatch):
    _con_claves(monkeypatch)
    base, texto = _base_con(False)
    monkeypatch.setattr(fm, "base_para_email", lambda email: base)
    status, cuerpo = _carta()
    assert status == 200 and cuerpo["cv_master_usado"] is False
    assert texto not in entorno[0]


def test_a_neon_master_with_ai_consent_reaches_the_prompt(entorno, monkeypatch):
    _con_claves(monkeypatch)
    base, texto = _base_con(True)
    monkeypatch.setattr(fm, "base_para_email", lambda email: base)
    status, _ = _carta()
    assert status == 200 and texto in entorno[0]
