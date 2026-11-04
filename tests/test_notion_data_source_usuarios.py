"""Hotfix: the Users database now has two data sources, so every Users call goes
through the Users data source with Notion-Version 2025-09-03. Ofertas and pages stay
on 2022-06-28.
"""
import pytest
import requests

import notion

DS = "34811515-f4b2-80d6-875a-000b7b858306"
NUEVA = "2025-09-03"
VIEJA = "2022-06-28"


class _Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = text

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


DB_DOS_FUENTES = {"data_sources": [{"id": DS, "name": "Users"},
                                   {"id": "otra-fuente", "name": "Ofertas de Trabajo"}]}


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(notion, "NOTION_TOKEN", "tok")
    monkeypatch.setattr(notion, "NOTION_DB_USUARIOS", "db-usuarios")
    monkeypatch.setattr(notion, "NOTION_DS_USUARIOS", DS)
    notion.reiniciar_caches()
    yield
    notion.reiniciar_caches()


@pytest.fixture
def red(monkeypatch):
    estado = {"posts": [], "gets": [], "get_resp": _Resp(200, {"properties": {}}),
              "post_resp": _Resp(200, {"results": []})}

    def post(url, headers=None, json=None, timeout=None):
        estado["posts"].append((url, headers, json))
        return estado["post_resp"]

    def get(url, headers=None, timeout=None):
        estado["gets"].append((url, headers))
        return estado["get_resp"]

    monkeypatch.setattr(notion.requests, "post", post)
    monkeypatch.setattr(notion.requests, "get", get)
    return estado


# --- headers ----------------------------------------------------------------------------

def test_default_headers_keep_the_old_version():
    assert notion.notion_headers()["Notion-Version"] == VIEJA


def test_headers_accept_an_explicit_version():
    assert notion.notion_headers(NUEVA)["Notion-Version"] == NUEVA


# --- calls ------------------------------------------------------------------------------

def test_user_lookup_queries_the_data_source(red):
    notion.buscar_usuario_por_email("x@y.com")
    url, headers, _ = red["posts"][0]
    assert url == f"https://api.notion.com/v1/data_sources/{DS}/query"
    assert headers["Notion-Version"] == NUEVA


def test_schema_is_read_from_the_data_source(red):
    notion._campos_alias_existentes()
    url, headers = red["gets"][0]
    assert url == f"https://api.notion.com/v1/data_sources/{DS}"
    assert headers["Notion-Version"] == NUEVA


def test_active_users_query_the_data_source_with_pagination(red):
    red["post_resp"] = _Resp(200, {"results": [], "has_more": False})
    assert notion.usuarios_activos() == []
    url, headers, cuerpo = red["posts"][0]
    assert url == f"https://api.notion.com/v1/data_sources/{DS}/query"
    assert headers["Notion-Version"] == NUEVA
    assert cuerpo["filter"] == {"property": "Activo", "checkbox": {"equals": True}}


def test_creating_a_user_uses_the_data_source_as_parent(red):
    red["post_resp"] = _Resp(200, {"id": "nueva"})
    notion.crear_usuario_en_notion({"nombre": "Ana", "email": "a@b.com"})
    url, headers, cuerpo = red["posts"][0]
    assert url == "https://api.notion.com/v1/pages"
    assert headers["Notion-Version"] == NUEVA
    assert cuerpo["parent"] == {"type": "data_source_id", "data_source_id": DS}


def test_offers_keep_the_old_version_and_database_endpoint(red, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DB_OFERTAS", "db-ofertas")
    notion.ofertas_por_puntuar("ella")
    url, headers, _ = red["posts"][0]
    assert url == "https://api.notion.com/v1/databases/db-ofertas/query"
    assert headers["Notion-Version"] == VIEJA


# --- resolution -------------------------------------------------------------------------

def test_a_configured_data_source_skips_resolution(red):
    assert notion.ds_usuarios() == DS
    assert red["gets"] == []


def test_resolution_picks_the_data_source_named_users(red, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DS_USUARIOS", "")
    red["get_resp"] = _Resp(200, DB_DOS_FUENTES)
    assert notion.ds_usuarios() == DS
    url, headers = red["gets"][0]
    assert url == "https://api.notion.com/v1/databases/db-usuarios"
    assert headers["Notion-Version"] == NUEVA


def test_resolution_is_cached(red, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DS_USUARIOS", "")
    red["get_resp"] = _Resp(200, DB_DOS_FUENTES)
    notion.ds_usuarios()
    notion.ds_usuarios()
    assert len(red["gets"]) == 1


def test_a_single_data_source_is_used_whatever_its_name(red, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DS_USUARIOS", "")
    red["get_resp"] = _Resp(200, {"data_sources": [{"id": "unica", "name": "Gente"}]})
    assert notion.ds_usuarios() == "unica"


@pytest.mark.parametrize("fuentes", [
    [],
    [{"id": "a", "name": "Ofertas"}, {"id": "b", "name": "Otra"}],
    [{"id": "a", "name": "Users"}, {"id": "b", "name": "Users"}],
])
def test_ambiguous_or_missing_data_sources_fail_closed(red, monkeypatch, fuentes):
    monkeypatch.setattr(notion, "NOTION_DS_USUARIOS", "")
    red["get_resp"] = _Resp(200, {"data_sources": fuentes})
    with pytest.raises(notion.DataSourceUsuariosError):
        notion.ds_usuarios()


def test_a_failed_resolution_is_not_cached(red, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DS_USUARIOS", "")
    red["get_resp"] = _Resp(500)
    with pytest.raises(notion.DataSourceUsuariosError):
        notion.ds_usuarios()
    red["get_resp"] = _Resp(200, DB_DOS_FUENTES)
    assert notion.ds_usuarios() == DS


def test_failed_resolution_makes_the_lookup_fail_without_querying(red, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DS_USUARIOS", "")
    red["get_resp"] = _Resp(200, {"data_sources": []})
    assert notion._consultar_usuario_ok({"property": "Email"}, "x@y.com", False) == (None, False)
    assert red["posts"] == []
