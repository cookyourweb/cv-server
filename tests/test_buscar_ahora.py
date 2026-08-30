"""TDD - "Buscar ahora" tiene que disparar una busqueda de verdad, y avisar cuando no.

Caso real (28ago2026). Barridos nodo a nodo los 10 workflows de la instancia n8n,
los paths `buscar-ahora` y `nuevo-usuario` NO EXISTEN en ninguno. El unico webhook
vivo que lanza una busqueda para un usuario concreto es `buscar-para-user`, dentro
del workflow de produccion `CsvmtPcLVmGIZg6C`.

Eran DOS fallos, no uno:

1. Se llamaba a un webhook inexistente.
2. El fallo era MUDO. El `except` escribia un warning con el comentario
   "no critico" y `/accion-existente` devolvia `{"ok": true}` igual. La persona
   pulsa "Buscar ahora", no pasa absolutamente nada, y la aplicacion le dice
   que si. Un endpoint que miente sobre lo que ha hecho es peor que uno que falla.

El contrato del payload NO es invento: sale del nodo `Code — Normalizar users
(schedule)` del propio workflow, que es como entra el disparo de las 9:00.
"""
import server as srv

USUARIO_NOTION = {
    "notion_id":     "3c011515-f4b2-810f-822c-d65fd09b56f0",
    "nombre":        "Veronica Serna",
    "email":         "veronica@cookyourwebai.es",
    "perfil":        "Frontend senior con IA en produccion",
    "rol":           "AI Engineer",
    "stack":         ["React", "TypeScript", "Python"],
    "salario_min":   55000,
    "modalidad":     ["Remoto"],
    "ciudad":        "Madrid",
    "linkedin":      "https://linkedin.com/in/veronicaserna",
    "cv_master_url": "https://docs.google.com/document/d/xxx",
}


class RespuestaFalsa:
    def __init__(self, status):
        self.status_code = status
        self.text = ""


# ── El contrato con el workflow ───────────────────────────────────────────

def test_el_payload_lleva_las_claves_que_espera_el_workflow():
    p = srv.payload_buscar_para_user(USUARIO_NOTION)
    for clave in ("user_id", "nombre", "email", "email_usuario", "perfil", "rol",
                  "stack", "salario", "modalidad", "ciudad", "linkedin",
                  "cv_master_url", "source"):
        assert clave in p, f"falta {clave} en el payload"


def test_salario_min_viaja_como_salario():
    # En Notion la propiedad es `Salario min`; el workflow la lee como `salario`.
    assert srv.payload_buscar_para_user(USUARIO_NOTION)["salario"] == 55000


def test_notion_id_viaja_como_user_id():
    p = srv.payload_buscar_para_user(USUARIO_NOTION)
    assert p["user_id"] == USUARIO_NOTION["notion_id"]


def test_acepta_tambien_el_formulario_de_alta():
    # El alta manda `rol_objetivo` y `salario`, no `rol` ni `salario_min`.
    p = srv.payload_buscar_para_user({"rol_objetivo": "AI Engineer", "salario": 60000})
    assert p["rol"] == "AI Engineer"
    assert p["salario"] == 60000


def test_el_source_dice_de_donde_viene():
    # El disparo de las 9:00 marca `schedule`. Este tiene que distinguirse.
    assert srv.payload_buscar_para_user(USUARIO_NOTION)["source"] == "cv-server"


def test_no_manda_el_perfil_vacio():
    # Sin perfil, n8n buscaria ofertas para nadie. Era lo que pasaba mandando
    # solo email y nombre.
    p = srv.payload_buscar_para_user(USUARIO_NOTION)
    assert p["perfil"] and p["stack"] and p["rol"]


# ── El disparo, y decir la verdad cuando falla ────────────────────────────

def test_disparar_devuelve_true_si_n8n_acepta(monkeypatch):
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: RespuestaFalsa(200))
    assert srv.disparar_busqueda(USUARIO_NOTION).disparada is True


def test_disparar_devuelve_false_si_el_webhook_no_existe(monkeypatch):
    # Exactamente el caso de hoy: el path no esta dado de alta, n8n responde 404.
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-ahora")
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: RespuestaFalsa(404))
    assert srv.disparar_busqueda(USUARIO_NOTION).disparada is False


def test_disparar_devuelve_false_si_la_red_falla(monkeypatch):
    def explota(*a, **k):
        raise srv.requests.exceptions.Timeout("timeout")
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv.requests, "post", explota)
    assert srv.disparar_busqueda(USUARIO_NOTION).disparada is False


def test_disparar_devuelve_false_sin_usuario():
    assert srv.disparar_busqueda(None).disparada is False


# ── El endpoint no puede decir que si cuando es que no ────────────────────

def _accion(monkeypatch, status, usuario=USUARIO_NOTION):
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: usuario)
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: RespuestaFalsa(status))
    with srv.app.test_client() as c:
        return c.post("/accion-existente",
                      json={"email": "veronica@cookyourwebai.es", "accion": "ahora"}).get_json()


def test_accion_existente_confirma_la_busqueda_cuando_se_dispara(monkeypatch):
    assert _accion(monkeypatch, 200)["busqueda_disparada"] is True


def test_accion_existente_no_miente_cuando_el_webhook_falla(monkeypatch):
    r = _accion(monkeypatch, 404)
    assert r["busqueda_disparada"] is False


def test_accion_existente_no_miente_si_el_usuario_no_esta(monkeypatch):
    assert _accion(monkeypatch, 200, usuario=None)["busqueda_disparada"] is False


def test_programar_manana_no_dispara_busqueda(monkeypatch):
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: USUARIO_NOTION)
    with srv.app.test_client() as c:
        r = c.post("/accion-existente",
                   json={"email": "veronica@cookyourwebai.es", "accion": "manana"}).get_json()
    assert r["busqueda_disparada"] is False
    assert r["ok"] is True


# ── La pantalla tampoco puede cantar exito sin mirar la respuesta ─────────

def _pagina():
    with srv.app.test_client() as c:
        return c.get("/").get_data(as_text=True)


def test_la_pantalla_no_tira_la_respuesta_del_servidor():
    # `accionExistente` hacia `await resp.json();` sin guardar nada y pintaba
    # "Buscando ahora mismo" igual. Arreglar el backend no servia de nada:
    # el mensaje no dependia de lo que contestara.
    # La comprobacion es que TODA lectura de la respuesta se asigne a algo.
    pagina = _pagina()
    assert pagina.count("await resp.json();") == pagina.count("= await resp.json();")


def test_la_pantalla_mira_si_la_busqueda_se_disparo():
    assert "busqueda_disparada" in _pagina()


# ── El timeout: n8n no contesta hasta terminar el workflow entero ─────────

def test_espera_lo_suficiente_para_que_n8n_termine(monkeypatch):
    """Medido en produccion el 28-ago-2026: la ejecucion 40530 tardo 10,7s.

    El webhook `buscar-para-user` esta en `responseMode: lastNode`, o sea que n8n
    NO responde hasta acabar los 15 nodos: consultar Notion y llamar a tres
    fuentes de ofertas. Con `timeout=8` el cv-server se rendia 2,7 segundos antes
    de tiempo, y la pantalla decia "no se ha podido lanzar la busqueda" cuando la
    busqueda SI se habia lanzado y termino en success.

    Mentir diciendo que no cuando si es menos grave que al reves, pero sigue
    siendo mentir.
    """
    capturado = {}

    def _post(url, **kwargs):
        capturado["timeout"] = kwargs.get("timeout")
        return RespuestaFalsa(200)

    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv.requests, "post", _post)
    srv.disparar_busqueda(USUARIO_NOTION)

    assert capturado["timeout"] >= 30, (
        f"timeout de {capturado['timeout']}s: el workflow tarda ~11s y puede ir mas "
        "lento si Render esta frio"
    )


def test_el_formulario_no_se_cachea():
    """El navegador servia el HTML viejo despues de desplegar el arreglo.

    Caso real del 28-ago-2026: el codigo desplegado leia `busqueda_disparada`
    correctamente, pero la pantalla seguia mostrando el mensaje anterior porque
    el navegador tenia la pagina en cache. Como el HTML lleva dentro el
    JavaScript, una pagina cacheada es LOGICA cacheada.
    """
    with srv.app.test_client() as c:
        cabecera = c.get("/").headers.get("Cache-Control", "")
    assert "no-store" in cabecera, f"Cache-Control='{cabecera}'"


# ── La espera se ve: 11 segundos de pantalla muerta no valen ──────────────
# OJO: la primera version de estos tests buscaba "disabled" y "Buscando" en toda
# la pagina, y PASABA estando el fallo presente, porque esas cadenas ya existian
# en otras pantallas. Un test que pasa a la primera con el codigo mal no prueba
# nada: hay que atarlo a la funcion concreta.


def _accion_existente():
    """El cuerpo de `accionExistente`, que es la funcion que tarda 11 segundos."""
    with srv.app.test_client() as c:
        pagina = c.get("/").get_data(as_text=True)
    ini = pagina.index("async function accionExistente")
    fin = pagina.index("function ", ini + 30)
    return pagina[ini:fin]


def test_los_botones_se_deshabilitan_mientras_se_espera():
    """Sin esto se puede pulsar dos veces y lanzar dos busquedas.

    `/accion-existente` tarda lo que tarde n8n en recorrer sus 15 nodos: medido
    entre 5,3 y 10,7 segundos. Durante ese rato la pantalla no hacia nada, asi
    que parecia colgada.
    """
    cuerpo = _accion_existente()
    assert "disabled = true" in cuerpo, "los botones siguen pulsables durante la espera"


def test_se_avisa_de_que_esta_buscando():
    assert "Buscando" in _accion_existente(), "no se avisa de que la busqueda esta en marcha"


def test_los_botones_se_reactivan_pase_lo_que_pase():
    # Dejar la pantalla bloqueada tras un error es peor que no bloquearla.
    assert "finally" in _accion_existente(), "sin `finally` un error deja los botones muertos"


def test_el_selector_apunta_a_la_pantalla_que_existe():
    """El primer intento uso `#s2a`, que NO existe: la pantalla es `#sExistente`.

    Los tests miran el texto del HTML, no ejecutan el JavaScript, asi que un
    selector equivocado los pasa igual. `querySelectorAll` de algo inexistente
    devuelve una lista vacia y no lanza: falla en silencio.
    """
    pagina = _html_completo()
    for selector in ("#sExistente", "#sEmail", "#s1", "#s2", "#sListo"):
        assert f'id="{selector[1:]}"' in pagina, f"{selector} no existe en la pagina"
    assert "#s2a" not in pagina, "selector `#s2a`: esa pantalla no existe"


def _html_completo():
    with srv.app.test_client() as c:
        return c.get("/").get_data(as_text=True)


# ── n8n devuelve 500 cuando el workflow no produce ofertas nuevas ─────────

class RespuestaSinItems:
    """Lo que devuelve n8n cuando el workflow acaba sin items que retornar."""
    status_code = 500
    text = '{"code":0,"message":"No item to return was found"}'


def test_no_hay_ofertas_nuevas_NO_es_un_fallo(monkeypatch):
    """Medido en produccion el 28-ago-2026.

    El webhook esta en `responseMode: lastNode`, asi que n8n devuelve lo que
    produzca el ultimo nodo. Cuando el dedup descarta todas las ofertas porque
    ya estaban en Notion, ese nodo devuelve CERO items y n8n responde:

        HTTP 500 {"code":0,"message":"No item to return was found"}

    El workflow acabo en `success` (ejecucion 40550, 11 nodos, 6 segundos): la
    busqueda SE HIZO. Tratar ese 500 como fallo hacia que la pantalla dijera "no
    se ha podido lanzar la busqueda" cuando si se habia lanzado.

    Un 500 con ESE mensaje concreto significa "hecho, sin novedades".
    """
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: RespuestaSinItems())
    assert srv.disparar_busqueda(USUARIO_NOTION).disparada is True


def test_un_500_de_verdad_sigue_siendo_un_fallo(monkeypatch):
    class ErrorReal:
        status_code = 500
        text = '{"message":"Workflow could not be started"}'

    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: ErrorReal())
    assert srv.disparar_busqueda(USUARIO_NOTION).disparada is False


def test_un_404_sigue_siendo_un_fallo(monkeypatch):
    # El webhook que no existe: el bug original de esta manana.
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-ahora")
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: RespuestaFalsa(404))
    assert srv.disparar_busqueda(USUARIO_NOTION).disparada is False


def test_se_distingue_buscada_de_hay_ofertas_nuevas(monkeypatch):
    """"Recibiras las ofertas" seria mentira si el dedup no dejo ninguna nueva.

    Son dos cosas distintas y la pantalla tiene que poder decir cual: la busqueda
    se hizo (`busqueda_disparada`) y ademas encontro algo (`hay_novedades`).
    """
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: USUARIO_NOTION)
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: RespuestaSinItems())
    with srv.app.test_client() as c:
        r = c.post("/accion-existente",
                   json={"email": "veronica@cookyourwebai.es", "accion": "ahora"}).get_json()
    assert r["busqueda_disparada"] is True
    assert r["hay_novedades"] is False


def test_la_pantalla_tiene_TRES_estados():
    """Se lanzo y hay novedades, se lanzo y no hay, y no se pudo lanzar."""
    cuerpo = _accion_existente()
    assert "hay_novedades" in cuerpo, "la pantalla no distingue si encontro algo"
    assert "no hay ofertas nuevas" in cuerpo


# ── El webhook va autenticado ─────────────────────────────────────────────
# 30ago2026. `buscartrabajo` y `cv-server` son repositorios PUBLICOS, y en sus
# docs esta tanto la URL del webhook como el `user_id` de Notion. El webhook
# `buscar-para-user` no pedia NADA: cualquiera que leyera el repositorio podia
# lanzar busquedas, gastar la cuota de Groq y de Adzuna y llenar el Notion.
# Comprobado disparandolo con `curl` a pelo, sin credenciales.
#
# n8n solo admite Basic, Header o JWT en un webhook, asi que va por cabecera.
# El token NO puede estar en el codigo (el repositorio es publico): sale del
# entorno, y si no esta, la cabecera no se manda. Ese silencio es a proposito:
# permite desplegar cv-server ANTES de activar la autenticacion en n8n, sin que
# el boton deje de funcionar en el medio.

class PostEspia:
    def __init__(self, status=200):
        self.status, self.kwargs = status, None
    def __call__(self, *a, **k):
        self.kwargs = k
        return RespuestaFalsa(self.status)


def test_el_disparo_manda_el_token_en_la_cabecera(monkeypatch):
    espia = PostEspia()
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv, "N8N_WEBHOOK_TOKEN", "un-token-de-prueba")
    monkeypatch.setattr(srv.requests, "post", espia)

    srv.disparar_busqueda(USUARIO_NOTION)

    assert espia.kwargs["headers"]["X-Webhook-Token"] == "un-token-de-prueba"


def test_sin_token_configurado_no_se_manda_cabecera_vacia(monkeypatch):
    # Una cabecera vacia es peor que ninguna: n8n la ve presente y la rechaza,
    # y el fallo parece de red en vez de configuracion.
    espia = PostEspia()
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv, "N8N_WEBHOOK_TOKEN", "")
    monkeypatch.setattr(srv.requests, "post", espia)

    srv.disparar_busqueda(USUARIO_NOTION)

    assert "X-Webhook-Token" not in espia.kwargs.get("headers", {})


def test_el_token_no_esta_escrito_en_el_codigo():
    # El repositorio es publico: el valor sale del entorno, nunca del fichero.
    import inspect, re
    fuente = inspect.getsource(srv)
    linea = [l for l in fuente.splitlines() if l.startswith("N8N_WEBHOOK_TOKEN")]
    assert linea, "falta N8N_WEBHOOK_TOKEN"
    assert re.search(r'os\.getenv\(\s*"N8N_WEBHOOK_TOKEN"', linea[0]), linea[0]
    assert not re.search(r'=\s*"[A-Za-z0-9_\-]{12,}"', linea[0]), "token escrito a mano"
