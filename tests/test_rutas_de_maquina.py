"""TDD - Las rutas que gastan IA o escriben datos solo las llama n8n, con la clave.

Caso real (2-3oct2026): /generar-cv y /generar-carta estaban abiertas. Cualquiera
que conociera la URL generaba un CV a nombre de otra usuaria (el email sale del
cuerpo de la peticion) y lo pagaba la clave de Claude de la duena (unos 0,05 USD
por CV). /buscar-ofertas-reales gastaba Groq y /crear-oferta escribia en Notion,
y no las llama nadie.

Las cuatro exigen la cabecera X-Clave-Maquina (ADR-003). Las tres del formulario
de alta siguen abiertas: las llama el navegador, y una clave en el navegador no
protege nada. Se cerraran con la identidad de las personas (OIDC).

El test del inventario es el que importa a largo plazo: una ruta nueva no puede
nacer abierta sin que alguien lo decida en la lista PUBLICAS.
"""
import pytest

import server as srv

CLAVE = "clave-de-prueba-larga-y-aleatoria"
RUTAS_DE_MAQUINA = ["/generar-cv", "/generar-carta", "/crear-oferta", "/buscar-ofertas-reales"]
PUBLICAS = {"/", "/health", "/check-email", "/registro", "/accion-existente", "/static/<path:filename>"}
# /yo no usa la clave de maquina: se protege con el token de Google de la usuaria.
PUBLICAS.add("/yo")
DATOS = {"email": "a@b.com", "empresa": "ACME", "puesto": "Frontend", "descripcion": "React"}


@pytest.fixture
def llamadas(monkeypatch):
    """Sustituye todo lo que cuesta dinero o escribe datos, y cuenta las llamadas."""
    registro = []

    def apunta(nombre, valor):
        def falso(*a, **k):
            registro.append(nombre)
            return valor
        return falso

    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    monkeypatch.setattr(srv, "generar_cv_core", apunta("generar_cv_core", {"ok": True}))
    monkeypatch.setattr(srv, "call_llm", apunta("call_llm", srv.RespuestaLLM("x", "m")))
    monkeypatch.setattr(srv, "call_llm_calidad", apunta("call_llm_calidad", srv.RespuestaLLM("x", "m")))
    for nombre in ("buscar_ofertas_reales", "crear_oferta_en_notion", "buscar_usuario_por_email"):
        if hasattr(srv, nombre):
            monkeypatch.setattr(srv, nombre, apunta(nombre, None))
    return registro


@pytest.fixture
def cliente(llamadas):
    with srv.app.test_client() as c:
        yield c


@pytest.mark.parametrize("ruta", RUTAS_DE_MAQUINA)
def test_ruta_de_maquina_sin_clave_responde_401(cliente, ruta):
    assert cliente.post(ruta, json=DATOS).status_code == 401


@pytest.mark.parametrize("ruta", RUTAS_DE_MAQUINA)
def test_ruta_de_maquina_con_clave_equivocada_responde_401(cliente, ruta):
    r = cliente.post(ruta, json=DATOS, headers={"X-Clave-Maquina": "otra"})
    assert r.status_code == 401


@pytest.mark.parametrize("ruta", RUTAS_DE_MAQUINA)
@pytest.mark.parametrize("configurada", ["", None])
def test_ruta_de_maquina_sin_clave_configurada_no_abre_nunca(monkeypatch, llamadas, ruta, configurada):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", configurada)
    with srv.app.test_client() as c:
        assert c.post(ruta, json=DATOS).status_code == 401
        assert c.post(ruta, json=DATOS, headers={"X-Clave-Maquina": ""}).status_code == 401


@pytest.mark.parametrize("ruta", RUTAS_DE_MAQUINA)
def test_sin_clave_no_se_gasta_ni_se_escribe_nada(cliente, llamadas, ruta):
    # Lo que protege el dinero y los datos: con 401, cero llamadas a modelos y a Notion.
    cliente.post(ruta, json=DATOS)
    assert llamadas == []


@pytest.mark.parametrize("ruta", RUTAS_DE_MAQUINA)
def test_con_la_clave_buena_pasa_el_decorador(cliente, ruta):
    r = cliente.post(ruta, json=DATOS, headers={"X-Clave-Maquina": CLAVE})
    assert r.status_code != 401


@pytest.mark.parametrize("ruta", ["/check-email", "/registro", "/accion-existente"])
def test_rutas_del_formulario_siguen_abiertas(cliente, ruta):
    # Las llama el navegador: si se cierran, el formulario de alta deja de funcionar.
    assert cliente.post(ruta, json={"email": "a@b.com"}).status_code != 401


def test_inventario_de_rutas():
    """Toda ruta que no este en PUBLICAS tiene que exigir la clave de maquina."""
    abiertas = []
    for regla in srv.app.url_map.iter_rules():
        if regla.rule in PUBLICAS:
            continue
        vista = srv.app.view_functions[regla.endpoint]
        if not getattr(vista, "exige_clave_maquina", False):
            abiertas.append(regla.rule)
    assert abiertas == [], f"Rutas abiertas sin decidirlo: {abiertas}"
