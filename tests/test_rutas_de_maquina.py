"""TDD - Las rutas que gastan IA o escriben datos solo las llama n8n, con la clave.

Caso real (2-3oct2026): /generar-cv y /generar-carta estaban abiertas. Cualquiera
que conociera la URL generaba un CV a nombre de otra usuaria (el email sale del
cuerpo de la peticion) y lo pagaba la clave de Claude de la duena (unos 0,05 USD
por CV). /buscar-ofertas-reales gastaba Groq y /crear-oferta escribia en Notion,
y no las llama nadie.

Las cinco exigen la cabecera X-Clave-Maquina (ADR-003). El 7-oct-2026 se cerro
el formulario de alta: /check-email y /accion-existente se borraron (permitian
enumerar emails y disparar busquedas ajenas) y /registro paso a exigir la clave,
y ya no devuelve el texto de la excepcion de Notion. Una clave en el navegador no
protege nada, asi que el alta de personas vendra con su identidad (OIDC).

El test del inventario es el que importa a largo plazo: una ruta nueva no puede
nacer abierta sin que alguien lo decida en la lista PUBLICAS.
"""
import pytest

import server as srv

CLAVE = "clave-de-prueba-larga-y-aleatoria"
RUTAS_DE_MAQUINA = ["/generar-cv", "/generar-carta", "/crear-oferta", "/buscar-ofertas-reales", "/registro"]
PUBLICAS = {"/", "/health", "/static/<path:filename>"}
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
    for nombre, valor in (
        ("buscar_ofertas_reales", None),
        ("crear_oferta_en_notion", None),
        ("buscar_usuario_por_email", None),
        ("crear_usuario_en_notion", {"id": "pagina-falsa"}),
        ("disparar_busqueda", srv.Resultado(False, hay_novedades=False)),
    ):
        monkeypatch.setattr(srv, nombre, apunta(nombre, valor))
    monkeypatch.setattr(srv.requests, "post", apunta("requests.post", None))
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


@pytest.mark.parametrize("ruta", ["/check-email", "/accion-existente"])
def test_rutas_retiradas_no_existen(cliente, ruta):
    # Cualquiera podia preguntar si un email existia y disparar busquedas ajenas.
    # Se borran, no se protegen: nadie legitimo las llama ya.
    assert cliente.post(ruta, json={"email": "a@b.com"}).status_code == 404
    assert cliente.get(ruta).status_code == 404


def test_registro_no_devuelve_la_excepcion(monkeypatch, cliente):
    # El texto de una excepcion de Notion puede traer ids, rutas o tokens.
    def revienta(*a, **k):
        raise Exception("ntn_detalle_interno")
    monkeypatch.setattr(srv, "crear_usuario_en_notion", revienta)
    r = cliente.post("/registro", json={"email": "ana@example.com"},
                     headers={"X-Clave-Maquina": CLAVE})
    assert r.status_code == 500
    assert "ntn_detalle_interno" not in r.get_data(as_text=True)


def test_registro_con_clave_crea_y_dispara(cliente, llamadas):
    r = cliente.post("/registro", json={"email": "ana@example.com", "nombre": "Ana"},
                     headers={"X-Clave-Maquina": CLAVE})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert "crear_usuario_en_notion" in llamadas
    assert "disparar_busqueda" in llamadas


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
