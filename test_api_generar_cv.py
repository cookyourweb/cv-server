"""TDD - API FastAPI de /generar-cv (ADR-001).

Testeamos la CAPA HTTP (validación Pydantic + mapeo de errores), no la
lógica de negocio: `generar_cv_core` se mockea, así no se tocan Drive/Notion/LLM.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

import api

client = TestClient(api.app)


def _payload(**over):
    p = {
        "email": "a@b.com",
        "empresa": "ACME",
        "puesto": "Frontend Engineer",
        "descripcion": "React, TypeScript",
        "idioma": "en",
    }
    p.update(over)
    return p


def test_faltan_campos_requeridos_da_422():
    # Pydantic rechaza el request si falta un campo requerido (empresa).
    r = client.post("/generar-cv", json={"email": "a@b.com", "puesto": "X"})
    assert r.status_code == 422


def test_campo_requerido_vacio_da_422():
    # empresa presente pero vacía -> min_length lo rechaza.
    r = client.post("/generar-cv", json=_payload(empresa=""))
    assert r.status_code == 422


def test_happy_path_devuelve_response_tipado():
    fake = {
        "ok": True,
        "link": "https://drive/x",
        "modelo_usado": "claude-haiku-4-5",
        "archivo": "cv.docx",
        "email": "a@b.com",
        "cv_master_usado": True,
        "idioma": "en",
        "cv_master_url": "https://drive/master",
    }
    with patch.object(api, "generar_cv_core", return_value=fake) as m:
        r = client.post("/generar-cv", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["archivo"] == "cv.docx"
    assert body["modelo_usado"] == "claude-haiku-4-5"
    m.assert_called_once()


def test_error_tipado_del_core_se_mapea():
    from cv_server_railway import CVError

    with patch.object(api, "generar_cv_core", side_effect=CVError(404, "Usuario no encontrado")):
        r = client.post("/generar-cv", json=_payload())
    assert r.status_code == 404
    assert r.json()["ok"] is False
    assert "no encontrado" in r.json()["error"].lower()
