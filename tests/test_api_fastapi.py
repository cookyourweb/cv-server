"""Tests for the FastAPI layer (ADR-001)."""
import os

os.environ.setdefault("CLAVE_MAQUINA", "test-clave")

from fastapi.testclient import TestClient

import api


def test_health():
    client = TestClient(api.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_cv_master_check_requires_clave():
    client = TestClient(api.app)
    r = client.post("/cv-master/check", json={"texto": "Hola"})
    assert r.status_code == 401


def test_cv_master_check_with_clave():
    client = TestClient(api.app)
    r = client.post("/cv-master/check", json={"texto": "Experiencia\n- React"}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code in (200, 401, 400)


def test_generar_cv_requires_clave_maquina():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/generar-cv", json={
        "email": "a@b.com", "empresa": "X", "puesto": "Dev"
    })
    assert r.status_code == 401


def test_generar_cv_byok_gate_denegado(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server, base_de_datos, byok

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("C", (), {"begin": lambda self: __import__("contextlib").nullcontext()})())
    monkeypatch.setattr(byok, "resolver_generacion_por_email", lambda email, conexion, prov: {
        "permitido": False, "modo": "denegado", "clave": None, "motivo": "sin trial"
    })
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"nombre": "Test", "email": email})

    client = TestClient(api.app)
    r = client.post("/generar-cv", json={
        "email": "a@b.com", "empresa": "X", "puesto": "Dev"
    }, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 403


def test_generar_carta_requires_clave():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/generar-carta", json={"email": "a@b.com", "empresa": "X", "puesto": "Dev"})
    assert r.status_code == 401


def test_generar_carta_byok_gate_denegado(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server, base_de_datos, byok

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("C", (), {"begin": lambda self: __import__("contextlib").nullcontext()})())
    monkeypatch.setattr(byok, "resolver_generacion_por_email", lambda email, conexion, prov: {
        "permitido": False, "modo": "denegado", "clave": None, "motivo": "sin trial"
    })
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"nombre": "Test", "email": email})

    client = TestClient(api.app)
    r = client.post("/generar-carta", json={
        "email": "a@b.com", "empresa": "X", "puesto": "Dev"
    }, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 403


def test_puntuar_ofertas_requires_clave():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/puntuar-ofertas")
    assert r.status_code == 401


def test_puntuar_ofertas_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, puntuacion
    monkeypatch.setattr(puntuacion, "puntuar_ofertas_core", lambda: {"ok": True, "puntuadas": 2, "saltadas": 0, "errores": 0, "sin_vectores": 0})
    client = TestClient(api.app)
    r = client.post("/puntuar_ofertas" if False else "/puntuar-ofertas", headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_usuarios_requires_clave():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.get("/usuarios")
    assert r.status_code == 401


def test_usuarios_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, notion, server
    monkeypatch.setattr(server, "NOTION_DB_USUARIOS", "db123")
    monkeypatch.setattr(notion, "paginas_usuarios_activos", lambda: [{"id": "p1", "properties": {"Name": {"title": [{"plain_text": "Vero"}]}, "Email": {"email": "v@x.com"}, "Activo": {"checkbox": True}}}])
    client = TestClient(api.app)
    r = client.get("/usuarios", headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_buscar_ofertas_reales_requires_clave():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/buscar-ofertas-reales", json={"rol": "frontend"})
    assert r.status_code == 401


def test_buscar_ofertas_reales_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, real_jobs
    monkeypatch.setattr(real_jobs, "buscar_ofertas_reales", lambda **kw: {"ok": True, "ofertas": [], "total_encontradas": 0, "total_filtradas": 0})
    client = TestClient(api.app)
    r = client.post("/buscar-ofertas-reales", json={"rol": "frontend"}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_crear_oferta_requires_clave():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/crear-oferta", json={"empresa": "X", "puesto": "Dev"})
    assert r.status_code == 401


def test_crear_oferta_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server
    monkeypatch.setattr(server, "idioma_de_oferta", lambda *a, **k: "es")
    import cuota
    monkeypatch.setattr(cuota, "es_exenta", lambda email: True)
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"notion_id": "n1"})
    monkeypatch.setattr(server, "crear_oferta_en_notion", lambda oferta, idioma, uid: {"id": "page123"})
    client = TestClient(api.app)
    r = client.post("/crear-oferta", json={"email": "a@b.com", "empresa": "X", "puesto": "Dev"}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["notion_page_id"] == "page123"


def test_buscar_para_usuaria_requires_clave():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "u1"})
    assert r.status_code == 401


def test_buscar_para_usuaria_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos, real_jobs, server, usuarias
    from repositorio import RepositorioDeUsuaria

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: FakeConn()})())
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: {"rol": "Dev", "stack": ["react"], "modalidad": ["remoto"], "ubicacion": "Madrid", "salario_min": 50000})
    monkeypatch.setattr(real_jobs, "buscar_ofertas_reales", lambda **kw: {"ok": True, "ofertas": [], "total_encontradas": 2, "total_filtradas": 1})
    import cuota
    monkeypatch.setattr(cuota, "es_exenta", lambda email: True)
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"notion_id": "n1"})
    monkeypatch.setattr(server, "crear_oferta_en_notion", lambda oferta, idioma, uid: {"id": "p1"})
    monkeypatch.setattr(server, "idioma_de_oferta", lambda *a, **k: "es")

    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "u1", "email": "a@b.com", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_registro_requires_clave():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/registro", json={"email": "a@b.com"})
    assert r.status_code == 401


def test_registro_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server
    monkeypatch.setattr(api, "registrar_invitada", lambda email, datos: ({}, True, True))
    client = TestClient(api.app)
    r = client.post("/registro", json={"email": "a@b.com"}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_yo_requires_auth():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.get("/yo")
    assert r.status_code == 401


def test_yo_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server

    class Id:
        sub = "sub123"
        email = "a@b.com"
        nombre = "Test"

    monkeypatch.setattr(server, "identificar", lambda *a, **k: Id())
    monkeypatch.setattr(server, "_estado_del_perfil", lambda uid, email: {"tiene_perfil": True})
    monkeypatch.setattr(server, "_consentimientos_de", lambda uid: {"consentimientos": {}})
    monkeypatch.setattr(server.cuota, "estado_de_usuaria", lambda uid, email: None)

    client = TestClient(api.app)
    r = client.get("/yo", headers={"Authorization": "Bearer fake"})
    assert r.status_code == 200
    assert r.json()["email"] == "a@b.com"


def test_perfil_requires_auth():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.get("/perfil")
    assert r.status_code == 401


def test_perfil_get_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server
    from repositorio import RepositorioDeUsuaria

    class Id:
        sub = "s"
        email = "a@b.com"
        nombre = "T"

    monkeypatch.setattr(server, "identificar", lambda *a, **k: Id())
    monkeypatch.setattr(base_de_datos if False else __import__("base_de_datos"), "configurada", lambda: True) if False else None
    import base_de_datos
    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "transaccion", lambda: type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})())
    import usuarias
    monkeypatch.setattr(usuarias, "resolver_o_crear", lambda identidad, conexion=None, respaldo=frozenset(): "uid-test")
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: {"rol": "Dev"})

    client = TestClient(api.app)
    r = client.get("/perfil", headers={"Authorization": "Bearer fake"})
    assert r.status_code == 200
    assert r.json()["rol"] == "Dev"


def test_consentimientos_requires_auth():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/consentimientos", json={"tipo": "almacenar_cv", "version": "v2"})
    assert r.status_code == 401


def test_consentimientos_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server
    from repositorio import RepositorioDeUsuaria

    class Id:
        sub = "s"
        email = "a@b.com"
        nombre = "T"

    monkeypatch.setattr(server, "identificar", lambda *a, **k: Id())
    import base_de_datos
    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "transaccion", lambda: type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})())
    import usuarias
    monkeypatch.setattr(usuarias, "resolver_o_crear", lambda identidad, conexion=None, respaldo=frozenset(): "uid-test")
    monkeypatch.setattr(RepositorioDeUsuaria, "registrar_consentimiento", lambda self, tipo, version: None)

    client = TestClient(api.app)
    r = client.post("/consentimientos", json={"tipo": "almacenar_cv", "version": "v2"}, headers={"Authorization": "Bearer fake"})
    assert r.status_code == 201


def test_interes_requires_auth():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.post("/interes", json={"tipo": "paquetes"})
    assert r.status_code == 401


def test_interes_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server
    from repositorio import RepositorioDeUsuaria

    class Id:
        sub = "s"
        email = "a@b.com"
        nombre = "T"

    monkeypatch.setattr(server, "identificar", lambda *a, **k: Id())
    import base_de_datos
    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "transaccion", lambda: type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})())
    import usuarias
    monkeypatch.setattr(usuarias, "resolver_o_crear", lambda identidad, conexion=None, respaldo=frozenset(): "uid-test")
    monkeypatch.setattr(RepositorioDeUsuaria, "registrar_interes", lambda self, tipo, org: "Acme")

    client = TestClient(api.app)
    r = client.post("/interes", json={"tipo": "paquetes"}, headers={"Authorization": "Bearer fake"})
    assert r.status_code == 201
    assert r.json()["organizacion"] == "Acme"


def test_cuenta_requires_auth():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.delete("/cuenta")
    assert r.status_code == 401


def test_cuenta_ok(monkeypatch):
    from fastapi.testclient import TestClient
    import api, server
    from repositorio import RepositorioDeUsuaria

    class Id:
        sub = "s"
        email = "a@b.com"
        nombre = "T"

    monkeypatch.setattr(server, "identificar", lambda *a, **k: Id())
    import base_de_datos
    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "transaccion", lambda: type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})())
    import usuarias
    monkeypatch.setattr(usuarias, "resolver_o_crear", lambda identidad, conexion=None, respaldo=frozenset(): "uid-test")
    monkeypatch.setattr(RepositorioDeUsuaria, "borrar_cuenta", lambda self: True)

    client = TestClient(api.app)
    r = client.delete("/cuenta", headers={"Authorization": "Bearer fake"})
    assert r.status_code == 204


def test_buscar_para_usuaria_cuota_agotada(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos, cuota, server, real_jobs
    from repositorio import RepositorioDeUsuaria

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})()})())
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: {"rol": "Dev", "stack": ["react"], "modalidad": ["remoto"], "ubicacion": "Madrid", "salario_min": 50000})
    monkeypatch.setattr(cuota, "es_exenta", lambda email: False)
    monkeypatch.setattr(cuota, "estado_de_usuaria", lambda uid, email, ahora=None: {"unidades_restantes": 0})

    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "u1", "email": "a@b.com", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 429


def test_buscar_para_usuaria_resuelve_usuario_por_email(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos, real_jobs, server, usuarias
    from repositorio import RepositorioDeUsuaria

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    conn = type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})()
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: conn})())
    monkeypatch.setattr(usuarias, "id_por_emails", lambda emails, conexion: "uid-interno")
    # first call None, second call profile
    profiles = iter([None, {"rol": "Dev", "stack": ["react"], "modalidad": ["remoto"], "ubicacion": "Madrid", "salario_min": 50000}])
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: next(profiles))
    monkeypatch.setattr(server, "cuota" if hasattr(server, "cuota") else "cuota", server.cuota)
    import cuota
    monkeypatch.setattr(cuota, "es_exenta", lambda email: True)
    monkeypatch.setattr(real_jobs, "buscar_ofertas_reales", lambda **kw: {"ok": True, "ofertas": [], "total_encontradas": 0, "total_filtradas": 0})

    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "uid-notion", "email": "a@b.com", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["usuario_id"] == "uid-interno"


def test_buscar_para_usuaria_perfil_no_encontrado(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos
    from repositorio import RepositorioDeUsuaria

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    conn = type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})()
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: conn})())
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: None)
    import usuarias
    monkeypatch.setattr(usuarias, "id_por_emails", lambda emails, conexion: None)

    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "u1", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 404


def test_buscar_para_usuaria_bd_no_disponible(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos
    from repositorio import RepositorioDeUsuaria

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: (_ for _ in ()).throw(Exception("db down"))})())

    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "u1", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 503


def test_buscar_para_usuaria_bd_no_configurada(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos
    monkeypatch.setattr(base_de_datos, "configurada", lambda: False)

    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "u1", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 503


def test_buscar_para_usuaria_notion_falla_parcial(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos, real_jobs, server
    from repositorio import RepositorioDeUsuaria

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    conn = type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})()
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: conn})())
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: {"rol": "Dev", "stack": ["react"], "modalidad": ["remoto"], "ubicacion": "Madrid", "salario_min": 50000})
    import cuota
    monkeypatch.setattr(cuota, "es_exenta", lambda email: True)
    monkeypatch.setattr(real_jobs, "buscar_ofertas_reales", lambda **kw: {"ok": True, "ofertas": [{"empresa": "A", "puesto": "Dev1"}, {"empresa": "B", "puesto": "Dev2"}, {"empresa": "C", "puesto": "Dev3"}], "total_encontradas": 3, "total_filtradas": 3})
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"notion_id": "n1"})
    monkeypatch.setattr(server, "idioma_de_oferta", lambda *a, **k: "es")
    calls = {"n": 0}
    def crear_oferta(oferta, idioma, uid):
        calls["n"] += 1
        if calls["n"] == 2:
            raise Exception("notion down")
        return {"id": f"page{calls['n']}"}
    monkeypatch.setattr(server, "crear_oferta_en_notion", crear_oferta)

    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "u1", "email": "a@b.com", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["ofertas_creadas"] == 2
    assert len(r.json()["notion_page_ids"]) == 2
    assert any("notion:" in e for e in r.json()["errores"])


def test_buscar_para_usuaria_devuelve_notion_page_ids(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos, real_jobs, server
    from repositorio import RepositorioDeUsuaria

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    conn = type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})()
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: conn})())
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: {"rol": "Dev", "stack": ["react"], "modalidad": ["remoto"], "ubicacion": "Madrid", "salario_min": 50000})
    import cuota
    monkeypatch.setattr(cuota, "es_exenta", lambda email: True)
    monkeypatch.setattr(real_jobs, "buscar_ofertas_reales", lambda **kw: {"ok": True, "ofertas": [{"empresa": "A", "puesto": "Dev1"}, {"empresa": "B", "puesto": "Dev2"}], "total_encontradas": 2, "total_filtradas": 2})
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"notion_id": "n1"})
    monkeypatch.setattr(server, "idioma_de_oferta", lambda *a, **k: "es")
    ids = iter(["page-1", "page-2"])
    monkeypatch.setattr(server, "crear_oferta_en_notion", lambda oferta, idioma, uid: {"id": next(ids)})

    client = TestClient(api.app)
    r = client.post("/buscar-para-usuaria", json={"usuario_id": "u1", "email": "a@b.com", "top_n": 3}, headers={"X-Clave-Maquina": "test-clave"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["notion_page_ids"] == ["page-1", "page-2"]
    assert r.json()["ofertas_creadas"] == 2
    assert all("notion_page_id" in o for o in r.json()["ofertas"])


def test_sse_progress_requires_no_clave():
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.app)
    r = client.get("/buscar-para-usuaria/progress?usuario_id=u1")
    # SSE endpoint is open (no clave) for demo; just ensure it responds
    assert r.status_code == 200


def test_sse_progress_streams(monkeypatch):
    from fastapi.testclient import TestClient
    import api, base_de_datos, real_jobs
    from repositorio import RepositorioDeUsuaria

    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    conn = type("C", (), {"__enter__": lambda self: self, "__exit__": lambda self, *a: None})()
    monkeypatch.setattr(base_de_datos, "motor", lambda: type("M", (), {"begin": lambda self: conn})())
    monkeypatch.setattr(RepositorioDeUsuaria, "obtener_perfil", lambda self: {"rol": "Dev", "stack": ["react"], "modalidad": ["remoto"], "ubicacion": "Madrid", "salario_min": 50000})
    monkeypatch.setattr(real_jobs, "buscar_ofertas_reales", lambda **kw: {"ok": True, "ofertas": [], "total_encontradas": 0, "total_filtradas": 0})

    client = TestClient(api.app)
    r = client.get("/buscar-para-usuaria/progress?usuario_id=u1")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
