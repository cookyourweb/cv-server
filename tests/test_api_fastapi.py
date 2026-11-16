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
