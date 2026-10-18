"""Notion side of the semantic-fit score: write `Encaje`/`Avisos`, list what is left to score.

Notion is faked at `requests`: no network.
"""
import pytest
import requests

import notion

BASE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ELLA = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class Respuesta:
    def __init__(self, estado=200, cuerpo=None):
        self.status_code = estado
        self._cuerpo = cuerpo or {}
        self.text = "no debe aparecer"

    def json(self):
        return self._cuerpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _rt(texto):
    return {"rich_text": [{"plain_text": texto}]}


def _pagina(pid="p1", empresa="Acme", puesto="Frontend", **extra):
    props = {
        "Empresa": {"title": [{"plain_text": empresa}]},
        "Puesto": _rt(puesto),
        "Descripción": {"rich_text": [{"plain_text": "React y "}, {"plain_text": "TypeScript"}]},
        "Salario": _rt("40k"),
        "Ubicación": _rt("Madrid"),
        "Modalidad": {"select": {"name": "Hibrido"}},
    }
    props.update(extra)
    return {"id": pid, "properties": props}


@pytest.fixture
def notion_falso(monkeypatch):
    monkeypatch.setattr(notion, "NOTION_TOKEN", "token")
    monkeypatch.setattr(notion, "NOTION_DB_OFERTAS", BASE)
    monkeypatch.setattr(notion, "NOTION_DB_USUARIOS", "dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    estado = {"posts": [], "patches": [], "respuestas": [Respuesta()]}

    def post(url, headers=None, json=None, timeout=None):
        assert timeout
        estado["posts"].append((url, json))
        r = estado["respuestas"].pop(0) if len(estado["respuestas"]) > 1 else estado["respuestas"][0]
        if isinstance(r, Exception):
            raise r
        return r

    def patch(url, headers=None, json=None, timeout=None):
        assert timeout
        estado["patches"].append((url, json))
        return estado.get("patch", Respuesta())

    monkeypatch.setattr(notion.requests, "post", post)
    monkeypatch.setattr(notion.requests, "patch", patch)
    return estado


# --- escribir_encaje ---------------------------------------------------------------------

def test_the_score_and_the_flags_are_written_to_the_offer_page(notion_falso):
    notion.escribir_encaje("pagina-1", 25, ["salario_bajo", "ubicacion"])
    url, cuerpo = notion_falso["patches"][0]
    assert url.endswith("/pages/pagina-1")
    assert cuerpo["properties"]["Encaje"] == {"number": 25}
    assert cuerpo["properties"]["Avisos"] == {"multi_select": [{"name": "salario_bajo"}, {"name": "ubicacion"}]}


def test_no_flags_writes_an_empty_multi_select(notion_falso):
    notion.escribir_encaje("p", -13, [])
    assert notion_falso["patches"][0][1]["properties"]["Avisos"] == {"multi_select": []}


def test_a_zero_score_is_still_written_so_the_offer_is_not_scored_again(notion_falso):
    notion.escribir_encaje("p", 0, [])
    assert notion_falso["patches"][0][1]["properties"]["Encaje"] == {"number": 0}


def test_a_notion_error_while_writing_raises(notion_falso):
    notion_falso["patch"] = Respuesta(500)
    with pytest.raises(requests.RequestException):
        notion.escribir_encaje("p", 1, [])


# --- ofertas_por_puntuar -----------------------------------------------------------------

def test_it_asks_for_her_pending_offers_without_score(notion_falso):
    notion_falso["respuestas"] = [Respuesta(200, {"results": [_pagina()]})]
    notion.ofertas_por_puntuar(ELLA)
    url, cuerpo = notion_falso["posts"][0]
    assert url.endswith(f"/databases/{BASE}/query")
    filtros = cuerpo["filter"]["and"]
    assert {"property": "Usuario", "relation": {"contains": ELLA}} in filtros
    assert {"property": "Estado", "select": {"equals": "Pendiente"}} in filtros
    assert {"property": "Encaje", "number": {"is_empty": True}} in filtros
    assert cuerpo["page_size"] == 100


def test_the_limit_never_exceeds_one_hundred(notion_falso):
    notion.ofertas_por_puntuar(ELLA, limite=500)
    assert notion_falso["posts"][0][1]["page_size"] == 100


def test_each_offer_comes_back_as_a_flat_dict(notion_falso):
    notion_falso["respuestas"] = [Respuesta(200, {"results": [_pagina("p1")]})]
    assert notion.ofertas_por_puntuar(ELLA) == [{
        "page_id": "p1", "empresa": "Acme", "puesto": "Frontend",
        "descripcion": "React y TypeScript", "salario": "40k", "modalidad": "Hibrido", "ubicacion": "Madrid"}]


def test_missing_properties_become_empty_strings(notion_falso):
    notion_falso["respuestas"] = [Respuesta(200, {"results": [{"id": "p", "properties": {}}]})]
    assert notion.ofertas_por_puntuar(ELLA)[0]["modalidad"] == ""


def test_without_the_offers_database_it_fails_like_creating_an_offer(notion_falso, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DB_OFERTAS", "")
    with pytest.raises(requests.RequestException):
        notion.ofertas_por_puntuar(ELLA)
    assert notion_falso["posts"] == []


def test_a_notion_error_while_listing_raises(notion_falso):
    notion_falso["respuestas"] = [Respuesta(500)]
    with pytest.raises(requests.RequestException):
        notion.ofertas_por_puntuar(ELLA)


# --- usuarios_activos --------------------------------------------------------------------

def _usuaria(pid="u1", email="a@b.com", alias="", evitar="", activo=True):
    return {"id": pid, "properties": {
        "Name": {"title": [{"plain_text": "Ana"}]}, "Email": {"email": email},
        "Emails alias": _rt(alias), "Activo": {"checkbox": activo},
        "Perfil": _rt("Dev React"), "Salario min": {"number": 30000},
        "Ciudad": _rt("Madrid"), "Evitar": _rt(evitar)}}


def test_active_users_carry_their_profile_every_mailbox_and_the_avoid_text(notion_falso):
    notion_falso["respuestas"] = [Respuesta(200, {"results": [_usuaria(alias="x@y.com", evitar="data")]})]
    [u] = notion.usuarios_activos()
    assert u["notion_id"] == "u1" and u["salario_min"] == 30000 and u["ciudad"] == "Madrid"
    assert u["emails"] == ["a@b.com", "x@y.com"]
    assert u["evitar"] == "data"
    assert notion_falso["posts"][0][1]["filter"] == {"property": "Activo", "checkbox": {"equals": True}}


def test_a_user_without_the_avoid_field_has_none(notion_falso):
    pagina = _usuaria()
    del pagina["properties"]["Evitar"]
    notion_falso["respuestas"] = [Respuesta(200, {"results": [pagina]})]
    assert notion.usuarios_activos()[0]["evitar"] is None


def test_the_listing_follows_pagination(notion_falso):
    notion_falso["respuestas"] = [
        Respuesta(200, {"results": [_usuaria("u1")], "has_more": True, "next_cursor": "c2"}),
        Respuesta(200, {"results": [_usuaria("u2")], "has_more": False})]
    assert [u["notion_id"] for u in notion.usuarios_activos()] == ["u1", "u2"]
    assert notion_falso["posts"][1][1]["start_cursor"] == "c2"
