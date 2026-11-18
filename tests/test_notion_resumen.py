"""Tests for notion_resumen (Spec 002): read-only summary of pending offers."""
import unittest.mock as mock

import pytest

import notion_resumen


def _pagina(results, has_more=False, next_cursor=None):
    return {"results": results, "has_more": has_more, "next_cursor": next_cursor}


def _oferta_props(empresa="Acme", puesto="Dev", ubicacion="Madrid", salario="40k",
                  modalidad="Remoto", enlace="https://x", notas="", via="LinkedIn",
                  fecha="2026-01-01"):
    return {
        "id": "page-1",
        "properties": {
            "Empresa": {"type": "title", "title": [{"plain_text": empresa}]},
            "Puesto": {"type": "rich_text", "rich_text": [{"plain_text": puesto}]},
            "Ubicación": {"type": "rich_text", "rich_text": [{"plain_text": ubicacion}]},
            "Modalidad": {"type": "select", "select": {"name": modalidad}},
            "Salario": {"type": "rich_text", "rich_text": [{"plain_text": salario}]},
            "Link oferta": {"type": "url", "url": enlace},
            "Notas": {"type": "rich_text", "rich_text": [{"plain_text": notas}]},
            "Via envio": {"type": "select", "select": {"name": via}},
            "Fecha Publicacion": {"type": "date", "date": {"start": fecha}},
        },
    }


@mock.patch("notion_resumen.NOTION_DB_OFERTAS", "db-123")
@mock.patch("notion_resumen.requests.post")
def test_listar_vacio(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = _pagina([])
    mock_post.return_value.raise_for_status = lambda: None
    assert notion_resumen.listar_ofertas_pendientes() == []


@mock.patch("notion_resumen.NOTION_DB_OFERTAS", "db-123")
@mock.patch("notion_resumen.requests.post")
def test_listar_una_oferta(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = _pagina([_oferta_props()])
    mock_post.return_value.raise_for_status = lambda: None
    res = notion_resumen.listar_ofertas_pendientes()
    assert len(res) == 1
    assert res[0]["empresa"] == "Acme"
    assert res[0]["puesto"] == "Dev"
    assert res[0]["ubicacion"] == "Madrid"


@mock.patch("notion_resumen.NOTION_DB_OFERTAS", "db-123")
@mock.patch("notion_resumen.requests.post")
def test_listar_paginacion(mock_post):
    r1 = mock.MagicMock(status_code=200)
    r1.json.return_value = _pagina([_oferta_props(empresa="A")], has_more=True, next_cursor="cur")
    r1.raise_for_status = lambda: None
    r2 = mock.MagicMock(status_code=200)
    r2.json.return_value = _pagina([_oferta_props(empresa="B")])
    r2.raise_for_status = lambda: None
    mock_post.side_effect = [r1, r2]
    res = notion_resumen.listar_ofertas_pendientes()
    assert [o["empresa"] for o in res] == ["A", "B"]
    assert mock_post.call_count == 2


@mock.patch("notion_resumen.NOTION_DB_OFERTAS", "db-123")
@mock.patch("notion_resumen.requests.post")
def test_listar_error_http_lanza(mock_post):
    r = mock.MagicMock(status_code=500)
    r.raise_for_status.side_effect = Exception("boom")
    r.json.return_value = {}
    mock_post.return_value = r
    with pytest.raises(RuntimeError):
        notion_resumen.listar_ofertas_pendientes()


@mock.patch("notion_resumen.NOTION_DB_OFERTAS", "")
def test_listar_sin_db_lanza():
    with pytest.raises(RuntimeError):
        notion_resumen.listar_ofertas_pendientes()


def test_es_incompleta():
    assert notion_resumen.es_incompleta({"empresa": "", "puesto": "Dev"}) is True
    assert notion_resumen.es_incompleta({"empresa": "Acme", "puesto": ""}) is True
    assert notion_resumen.es_incompleta({"empresa": "Acme", "puesto": "Dev"}) is False


def test_resumen_vacio():
    md = notion_resumen.resumen_pendientes_markdown([])
    assert "No hay ofertas pendientes" in md


def test_resumen_con_oferta():
    ofertas = [{
        "empresa": "Acme", "puesto": "Dev", "ubicacion": "Madrid",
        "modalidad": "Remoto", "salario": "40k", "enlace": "https://x",
        "via_envio": "LinkedIn", "notas": "nota", "fecha_publicacion": "2026-01-01",
    }]
    md = notion_resumen.resumen_pendientes_markdown(ofertas)
    assert "Acme" in md and "Dev" in md
    assert "Total: 1" in md
    assert "incompleta" not in md


def test_resumen_marca_incompleta():
    ofertas = [{"empresa": "", "puesto": "Dev"}]
    md = notion_resumen.resumen_pendientes_markdown(ofertas)
    assert "incompleta" in md


@mock.patch("api.notion_resumen.listar_ofertas_pendientes")
def test_endpoint_ok(mock_listar, monkeypatch):
    import api
    import server
    monkeypatch.setattr(server, "CLAVE_MAQUINA", "clave-test")
    mock_listar.return_value = [{"empresa": "Acme", "puesto": "Dev"}]
    from fastapi.testclient import TestClient
    c = TestClient(api.app)
    r = c.get("/resumen-pendientes", headers={"X-Clave-Maquina": "clave-test"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["total"] == 1
    assert "Acme" in data["markdown"]


@mock.patch("api.notion_resumen.listar_ofertas_pendientes")
def test_endpoint_sin_clave_401(mock_listar, monkeypatch):
    import api
    import server
    monkeypatch.setattr(server, "CLAVE_MAQUINA", "clave-test")
    mock_listar.return_value = []
    from fastapi.testclient import TestClient
    c = TestClient(api.app)
    r = c.get("/resumen-pendientes")
    assert r.status_code == 401


@mock.patch("api.notion_resumen.listar_ofertas_pendientes")
def test_endpoint_fallo_notion_502(mock_listar, monkeypatch):
    import api
    import server
    monkeypatch.setattr(server, "CLAVE_MAQUINA", "clave-test")
    mock_listar.side_effect = RuntimeError("boom")
    from fastapi.testclient import TestClient
    c = TestClient(api.app)
    r = c.get("/resumen-pendientes", headers={"X-Clave-Maquina": "clave-test"})
    assert r.status_code == 502

