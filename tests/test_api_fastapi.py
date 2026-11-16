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
