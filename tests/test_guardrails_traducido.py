"""C10 - translated-master mode in guardrails.revisar.

When the master is in another language than the document, detectors that compare
literal text would raise false alarms. They are skipped and reported as
`no_evaluables`; the language-independent ones keep running.
"""
import pytest

import fuente_master as fm
import guardrails as g
import server as srv
from drive import MasterCV

# Every registered detector, classified on purpose. A new detector must be added here.
CLASIFICACION = {
    "cifras_no_respaldadas": True,
    "tecnologias_no_respaldadas": True,
    "skills_no_respaldadas": False,
    "experiencia_mal_atribuida": False,
    "inflacion": True,
    # Finds the PERFIL BASE by its Spanish section names and compares literal identities.
    "titular_fuera_de_contrato": False,
}


def test_every_detector_declares_its_classification():
    assert {d.nombre: d.independiente_del_idioma for d in g.GUARDRAILS} == CLASIFICACION


def test_no_evaluables_lists_the_text_matching_detectors_for_the_destination():
    assert g.no_evaluables(g.CV, traducido=True) == ["skills_no_respaldadas"]
    assert g.no_evaluables(g.CARTA, traducido=True) == ["experiencia_mal_atribuida"]


def test_no_evaluables_is_empty_when_not_translated():
    assert g.no_evaluables(g.CV) == [] and g.no_evaluables(g.CARTA, traducido=False) == []


def test_text_matching_detector_is_skipped_when_translated():
    cv = "TECHNICAL SKILLS\nFrontend: React · Zorkmid · Quuxlang"
    master = "Frontend con React."
    assert [a.regla for a in g.revisar(cv, master, g.CV)] == ["skills_no_respaldadas"]
    assert g.revisar(cv, master, g.CV, traducido=True) == []


def test_language_independent_detectors_still_fire_when_translated():
    texto = "Led a team of 45 engineers with Kubernetes. I was the sole owner."
    master = "Frontend con Angular, 3 años."
    reglas = {a.regla for a in g.revisar(texto, master, g.CV, traducido=True)}
    assert reglas == {"cifras_no_respaldadas", "tecnologias_no_respaldadas", "inflacion"}


def test_default_is_the_untranslated_behaviour():
    texto, master = "Stack: Kubernetes · Terraform. Sole owner, 45 users.", "Angular"
    assert g.revisar(texto, master, g.CV) == g.revisar(texto, master, g.CV, traducido=False)


# ── Route level ──────────────────────────────────────────────────────────────
CLAVE = "clave-de-prueba-larga-y-aleatoria"
DATOS = {"email": "vero@example.com", "empresa": "ACME", "puesto": "Frontend",
         "descripcion": "Angular " * 40, "idioma": "es"}
CARTA = "Lideré un equipo de 45 personas con Kubernetes. Tengo ocho años con React."


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    monkeypatch.setattr(srv, "buscar_oferta_en_notion", lambda e, p: None)
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: {"nombre": "Vero", "cv_master_url": ""})
    monkeypatch.setattr(srv, "call_llm_calidad", lambda p, **kw: srv.RespuestaLLM(CARTA, "modelo-falso"))
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", lambda u, i: MasterCV("", ""))

    def post():
        r = srv.app.test_client().post("/generar-carta", json=DATOS, headers={"X-Clave-Maquina": CLAVE})
        return r.status_code, r.get_json()
    return post


def _neon_en_ingles(monkeypatch, master="Frontend engineer. Angular, 8 years. Vue.js."):
    import base64
    import os
    import cifrado
    monkeypatch.setenv("CV_CLAVES", "1:" + base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "1")

    class Repo:
        usuario_id = "u-1"

        def tiene_consentimiento(self, tipo):
            return True

        def obtener_cv(self, idioma):
            if idioma != "en":
                return None
            v, n, c = cifrado.cifrar(master, "u-1", idioma)
            return type("F", (), {"clave_version": v, "nonce": n, "cifrado": c})()
    monkeypatch.setattr(fm, "base_para_email", lambda email: fm.MasterEnBase(Repo()))


def test_route_translated_master_skips_text_matching_and_keeps_figures_and_tech(cliente, monkeypatch):
    _neon_en_ingles(monkeypatch)
    status, cuerpo = cliente()
    assert status == 200 and cuerpo["master_traducido"] is True
    reglas = {a["regla"] for a in cuerpo["avisos"]}
    assert "experiencia_mal_atribuida" not in reglas
    assert {"cifras_no_respaldadas", "tecnologias_no_respaldadas"} <= reglas
    assert cuerpo["no_evaluables"] == ["experiencia_mal_atribuida"]


def test_route_legacy_flow_is_unchanged(cliente, monkeypatch):
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive",
                        lambda u, i: MasterCV("Frontend. Angular, 8 años. Vue.js.", "https://d/es"))
    status, cuerpo = cliente()
    assert status == 200 and cuerpo["master_traducido"] is False
    assert cuerpo["no_evaluables"] == []
    assert "experiencia_mal_atribuida" in {a["regla"] for a in cuerpo["avisos"]}


# ── CV route ─────────────────────────────────────────────────────────────────
def test_the_headline_detector_is_text_matching_and_belongs_to_the_headline_destination():
    assert g.no_evaluables(g.TITULAR, traducido=True) == ["titular_fuera_de_contrato"]
    assert g.no_evaluables(g.TITULAR) == []
    assert "titular_fuera_de_contrato" not in {d.nombre for d in g.guardrails_para(g.CV)}


PERFIL_BASE = """# PERFIL BASE

## Identidad profesional
Frontend Tech Lead | AI Engineer | React

## Identidades permitidas
- Frontend Tech Lead
- AI Engineer
"""
TITULAR_INVERTIDO = "AI Engineer | Frontend Tech Lead | React"
CV_SALIDA = ("HEADLINE: algo\nEXPERIENCIA\nLideré un equipo de 45 personas con Kubernetes. "
             "Fui el único responsable.\nTECHNICAL SKILLS\nFrontend: React · Zorkmid · Quuxlang")


@pytest.fixture
def cliente_cv(monkeypatch):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    monkeypatch.setattr(srv, "buscar_oferta_en_notion", lambda e, p: None)
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: {"nombre": "Vero", "cv_master_url": ""})
    monkeypatch.setattr(srv, "call_llm_calidad", lambda p, **kw: srv.RespuestaLLM(CV_SALIDA, "modelo-falso"))
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", lambda u, i: MasterCV("", ""))
    monkeypatch.setattr(srv, "construir_titular", lambda t, m: TITULAR_INVERTIDO)
    monkeypatch.setattr(srv, "generar_docx_con_cabecera", lambda *a, **k: b"docx")
    monkeypatch.setattr(srv, "subir_cv_a_drive", lambda b, n: "https://drive/cv")
    monkeypatch.setattr(srv, "guardar_link_cv_en_notion", lambda *a, **k: True)

    def post():
        r = srv.app.test_client().post("/generar-cv", json=DATOS, headers={"X-Clave-Maquina": CLAVE})
        return r.status_code, r.get_json()
    return post


def test_cv_route_translated_master_skips_text_matching_and_keeps_figures_and_tech(cliente_cv, monkeypatch, caplog):
    import logging
    _neon_en_ingles(monkeypatch, PERFIL_BASE)
    with caplog.at_level(logging.WARNING):
        status, cuerpo = cliente_cv()
    assert status == 200 and cuerpo["master_traducido"] is True
    assert cuerpo["titular_fuera_de_contrato"] == []
    assert "SKILLS NO RESPALDADAS" not in caplog.text and "TITULAR FUERA" not in caplog.text
    assert cuerpo["cifras_no_respaldadas"] and cuerpo["tecnologias_no_respaldadas"]
    assert cuerpo["no_evaluables"] == ["skills_no_respaldadas", "titular_fuera_de_contrato"]


def test_cv_route_legacy_flow_is_unchanged(cliente_cv, monkeypatch, caplog):
    import logging
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive",
                        lambda u, i: MasterCV(PERFIL_BASE + "\nFrontend. React.", "https://d/es"))
    monkeypatch.setattr(srv, "buscar_usuario_por_email",
                        lambda e: {"nombre": "Vero", "cv_master_url": "https://d/es"})
    with caplog.at_level(logging.WARNING):
        status, cuerpo = cliente_cv()
    assert status == 200 and cuerpo["master_traducido"] is False
    assert cuerpo["no_evaluables"] == []
    assert cuerpo["titular_fuera_de_contrato"]
    assert "SKILLS NO RESPALDADAS" in caplog.text
    assert cuerpo["cifras_no_respaldadas"] and cuerpo["tecnologias_no_respaldadas"]
