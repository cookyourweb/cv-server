"""TDD: the legacy Notion lookup must not hammer properties that do not exist.

Real local test, 11 Oct 2026: every GET /yo queried three alias properties missing from
the Usuarios database. Each one returned HTTP 400, logged a WARNING, and made sign-in
wait several seconds. The fix detects the schema once, remembers missing properties,
logs at most once, and caches the per-email result briefly.
"""
import logging

import pytest

import notion


class _Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = text

    def json(self):
        return self._body


def _pagina(email="vero@gmail.com", **extra):
    props = {"Email": {"email": email}, "Activo": {"checkbox": True}}
    props.update(extra)
    return {"id": "pg1", "properties": props}


SCHEMA_SIN_ALIAS = {"properties": {"Email": {"type": "email"}, "Name": {"type": "title"}}}
SCHEMA_CON_ALIAS = {"properties": {"Email": {"type": "email"},
                                   "Email alias": {"type": "rich_text"}}}
ERROR_400 = _Resp(400, text='{"message":"Could not find property with name or id: X"}')


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DB_USUARIOS", "db1")
    notion.reiniciar_caches()
    yield
    notion.reiniciar_caches()


@pytest.fixture
def red(monkeypatch):
    """Records every Notion call; behaviour is set per test."""
    estado = {"posts": [], "gets": 0, "schema": _Resp(200, SCHEMA_SIN_ALIAS),
              "responder": lambda filtro: _Resp(200, {"results": []})}

    def post(url, headers=None, json=None, timeout=None):
        estado["posts"].append(json["filter"])
        return estado["responder"](json["filter"])

    def get(url, headers=None, timeout=None):
        estado["gets"] += 1
        r = estado["schema"]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(notion.requests, "post", post)
    monkeypatch.setattr(notion.requests, "get", get)
    return estado


def _props_consultadas(red):
    return [f["property"] for f in red["posts"]]


def test_missing_alias_properties_are_not_queried(red):
    assert notion.buscar_usuario_por_email("x@y.com") is None
    assert _props_consultadas(red) == ["Email"]


def test_existing_alias_property_is_queried_with_its_real_name(red):
    red["schema"] = _Resp(200, SCHEMA_CON_ALIAS)
    notion.buscar_usuario_por_email("x@y.com")
    assert _props_consultadas(red) == ["Email", "Email alias"]


def test_schema_is_fetched_once_across_lookups(red):
    notion.buscar_usuario_por_email("a@y.com")
    notion.buscar_usuario_por_email("b@y.com")
    assert red["gets"] == 1


def test_schema_is_refetched_after_ttl(red, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(notion.time, "monotonic", lambda: t[0])
    notion.buscar_usuario_por_email("a@y.com")
    t[0] += notion.TTL_ESQUEMA + 1
    notion.buscar_usuario_por_email("b@y.com")
    assert red["gets"] == 2


def test_user_found_by_main_email_is_unchanged(red):
    red["responder"] = lambda f: _Resp(200, {"results": [_pagina()]})
    u = notion.buscar_usuario_por_email("vero@gmail.com")
    assert u["notion_id"] == "pg1" and u["email"] == "vero@gmail.com"
    assert _props_consultadas(red) == ["Email"]  # found at the first pass


def test_user_found_by_alias_when_the_property_exists(red):
    red["schema"] = _Resp(200, SCHEMA_CON_ALIAS)
    pag = _pagina("vero@gmail.com", **{"Email alias": {"rich_text": [{"plain_text": "otra@x.com"}]}})
    red["responder"] = lambda f: (_Resp(200, {"results": [pag]})
                                  if f["property"] == "Email alias" else _Resp(200, {"results": []}))
    assert notion.buscar_usuario_por_email("otra@x.com")["notion_id"] == "pg1"


def test_two_lookups_within_ttl_hit_notion_once(red):
    notion.buscar_usuario_por_email("vero@gmail.com")
    n = len(red["posts"])
    notion.buscar_usuario_por_email("vero@gmail.com")
    assert len(red["posts"]) == n


def test_lookup_is_refreshed_after_ttl(red, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(notion.time, "monotonic", lambda: t[0])
    notion.buscar_usuario_por_email("vero@gmail.com")
    n = len(red["posts"])
    t[0] += notion.TTL_USUARIO + 1
    notion.buscar_usuario_por_email("vero@gmail.com")
    assert len(red["posts"]) == 2 * n


def test_network_errors_are_not_cached(red):
    import requests
    llamadas = []

    def falla(f):
        llamadas.append(1)
        raise requests.ConnectionError("down")

    red["responder"] = falla
    assert notion.buscar_usuario_por_email("vero@gmail.com") is None
    assert notion.buscar_usuario_por_email("vero@gmail.com") is None
    assert len(llamadas) == 2


def test_http_errors_are_not_cached(red):
    red["responder"] = lambda f: _Resp(500, text="boom")
    notion.buscar_usuario_por_email("vero@gmail.com")
    notion.buscar_usuario_por_email("vero@gmail.com")
    assert len(red["posts"]) == 2


def test_schema_failure_falls_back_to_candidates_and_remembers_400(red, caplog):
    """If the schema cannot be read, try the candidates, but each 400 is remembered."""
    import requests
    red["schema"] = requests.ConnectionError("down")
    red["responder"] = lambda f: ERROR_400 if f["property"] != "Email" else _Resp(200, {"results": []})
    with caplog.at_level(logging.WARNING):
        notion.buscar_usuario_por_email("a@y.com")
        primera = len(red["posts"])
        notion.buscar_usuario_por_email("b@y.com")
    segunda = len(red["posts"]) - primera
    assert segunda == 1  # only "Email": the missing aliases are not retried
    avisos = [r for r in caplog.records if "property" in r.getMessage().lower()
              and r.levelno == logging.WARNING]
    assert len(avisos) == len(notion.campos_alias_candidatos())  # once per property, not per call


def test_property_not_found_warning_is_logged_at_most_once(red, caplog):
    red["schema"] = _Resp(200, {"properties": {"Email": {}, "Email alias": {}}})
    red["responder"] = lambda f: ERROR_400 if f["property"] == "Email alias" else _Resp(200, {"results": []})
    with caplog.at_level(logging.WARNING):
        for i in range(4):
            notion.buscar_usuario_por_email(f"u{i}@y.com")
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    assert _props_consultadas(red).count("Email alias") == 1
