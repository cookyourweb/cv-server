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
    assert srv.disparar_busqueda(USUARIO_NOTION) is True


def test_disparar_devuelve_false_si_el_webhook_no_existe(monkeypatch):
    # Exactamente el caso de hoy: el path no esta dado de alta, n8n responde 404.
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-ahora")
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: RespuestaFalsa(404))
    assert srv.disparar_busqueda(USUARIO_NOTION) is False


def test_disparar_devuelve_false_si_la_red_falla(monkeypatch):
    def explota(*a, **k):
        raise srv.requests.exceptions.Timeout("timeout")
    monkeypatch.setattr(srv, "WEBHOOK_BUSCAR_AHORA", "https://n8n.test/webhook/buscar-para-user")
    monkeypatch.setattr(srv.requests, "post", explota)
    assert srv.disparar_busqueda(USUARIO_NOTION) is False


def test_disparar_devuelve_false_sin_usuario():
    assert srv.disparar_busqueda(None) is False


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
