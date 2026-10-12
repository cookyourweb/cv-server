"""Reading an offer for its OWNER only (C13, ADR-009).

An offer is hers only if its "Usuario" relation holds her Notion page id. Anything else
(no owner, another owner, a page of another database, archived, missing, malformed id)
is the same answer: None. A Notion failure is ErrorDeNotion, never "not found", so the
route can fail closed. Notion is mocked: no real network.
"""
import pytest
import requests

import notion

BASE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ELLA = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTRA = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
O1 = "11111111-1111-4111-8111-111111111111"
O2 = "22222222-2222-4222-8222-222222222222"
O3 = "33333333-3333-4333-8333-333333333333"


def _pagina(pagina_id=O1, duenos=(ELLA,), base=BASE, archivada=False, **extra):
    props = {
        "Usuario": {"relation": [{"id": d} for d in duenos]},
        "Puesto": {"rich_text": [{"plain_text": "Frontend"}, {"plain_text": " Dev"}]},
        "Descripción": {"rich_text": [{"plain_text": "Angular y TypeScript"}]},
        "Tags": {"multi_select": [{"name": "RxJS"}]},
        "Idioma": {"select": {"name": "en"}},
    }
    props.update(extra)
    return {"id": pagina_id, "archived": archivada, "in_trash": False,
            "parent": {"type": "database_id", "database_id": base}, "properties": props}


class Respuesta:
    def __init__(self, estado=200, cuerpo=None, cabeceras=None):
        self.status_code = estado
        self._cuerpo = cuerpo
        self.headers = cabeceras or {}
        self.text = "no debe aparecer"

    def json(self):
        if self._cuerpo is None:
            raise ValueError("no json")
        return self._cuerpo


@pytest.fixture
def notion_falso(monkeypatch):
    """Notion configured; `paginas` maps a dashless page id to a Respuesta (or an exception)."""
    monkeypatch.setattr(notion, "NOTION_TOKEN", "token-de-prueba")
    monkeypatch.setattr(notion, "NOTION_DB_OFERTAS", BASE)
    monkeypatch.setattr(notion.time, "sleep", lambda s: None)
    estado = {"paginas": {}, "llamadas": []}

    def get(url, headers=None, timeout=None):
        estado["llamadas"].append(url)
        assert timeout, "every Notion call needs a timeout"
        r = estado["paginas"].get(url.rsplit("/", 1)[1], Respuesta(404, {"object": "error"}))
        if isinstance(r, Exception):
            raise r
        if isinstance(r, list):  # a sequence of answers, consumed one per call
            r = r.pop(0)
        return r

    monkeypatch.setattr(notion.requests, "get", get)
    return estado


def _plano(i):
    return i.replace("-", "")


def test_the_owner_gets_the_text_of_her_offer(notion_falso):
    notion_falso["paginas"][_plano(O1)] = Respuesta(200, _pagina())
    oferta = notion.leer_oferta_de_usuaria(O1, ELLA)
    assert oferta == {"puesto": "Frontend Dev", "descripcion": "Angular y TypeScript",
                      "tags": ["RxJS"], "idioma": "en"}


def test_ids_are_compared_ignoring_dashes_and_case(notion_falso):
    notion_falso["paginas"][_plano(O1)] = Respuesta(200, _pagina(duenos=(ELLA.upper(),)))
    assert notion.leer_oferta_de_usuaria(_plano(O1).upper(), _plano(ELLA)) is not None


@pytest.mark.parametrize("pagina", [
    _pagina(duenos=()),                      # no owner
    _pagina(duenos=(OTRA,)),                 # another owner
    _pagina(duenos=(OTRA, ELLA)[:1]),        # same, explicit
    _pagina(base=OTRA),                      # a page of ANOTHER database, even if it names her
    _pagina(archivada=True),                 # in the bin
    _pagina(Usuario={}),                     # relation property missing its payload
])
def test_everything_that_is_not_hers_is_none(notion_falso, pagina):
    notion_falso["paginas"][_plano(O1)] = Respuesta(200, pagina)
    assert notion.leer_oferta_de_usuaria(O1, ELLA) is None


@pytest.mark.parametrize("estado", [400, 403, 404])
def test_missing_or_invisible_pages_are_none(notion_falso, estado):
    notion_falso["paginas"][_plano(O1)] = Respuesta(estado, {"object": "error"})
    assert notion.leer_oferta_de_usuaria(O1, ELLA) is None


@pytest.mark.parametrize("malo", ["", "no-es-un-id", "../users", O1 + "/x", None, 7, "1" * 31])
def test_a_malformed_id_is_none_without_a_request(notion_falso, malo):
    assert notion.leer_oferta_de_usuaria(malo, ELLA) is None
    assert notion_falso["llamadas"] == []


def test_an_empty_owner_id_never_matches(notion_falso):
    notion_falso["paginas"][_plano(O1)] = Respuesta(200, _pagina(duenos=()))
    assert notion.leer_oferta_de_usuaria(O1, "") is None
    assert notion_falso["llamadas"] == []


@pytest.mark.parametrize("fallo", [
    Respuesta(500, {"object": "error"}), Respuesta(502), Respuesta(401, {"object": "error"}),
    Respuesta(200),  # 200 with a body that is not JSON
    requests.ConnectionError("boom"), requests.Timeout("slow"),
])
def test_a_notion_failure_is_an_error_never_not_found(notion_falso, fallo):
    notion_falso["paginas"][_plano(O1)] = fallo
    with pytest.raises(notion.ErrorDeNotion):
        notion.leer_oferta_de_usuaria(O1, ELLA)


@pytest.mark.parametrize("variable", ["NOTION_TOKEN", "NOTION_DB_OFERTAS"])
def test_unconfigured_notion_is_an_error_without_a_request(notion_falso, monkeypatch, variable):
    monkeypatch.setattr(notion, variable, "")
    with pytest.raises(notion.ErrorDeNotion):
        notion.leer_oferta_de_usuaria(O1, ELLA)
    assert notion_falso["llamadas"] == []


def test_a_rate_limit_is_retried_once(notion_falso):
    notion_falso["paginas"][_plano(O1)] = [Respuesta(429, {}, {"Retry-After": "1"}), Respuesta(200, _pagina())]
    assert notion.leer_oferta_de_usuaria(O1, ELLA) is not None
    assert len(notion_falso["llamadas"]) == 2


def test_a_second_rate_limit_is_an_error(notion_falso):
    notion_falso["paginas"][_plano(O1)] = [Respuesta(429), Respuesta(429)]
    with pytest.raises(notion.ErrorDeNotion):
        notion.leer_oferta_de_usuaria(O1, ELLA)


def test_the_batch_keeps_only_her_offers_keyed_by_plain_id(notion_falso):
    notion_falso["paginas"][_plano(O1)] = Respuesta(200, _pagina(O1))
    notion_falso["paginas"][_plano(O2)] = Respuesta(200, _pagina(O2, duenos=(OTRA,)))
    # O3 does not exist
    encontradas = notion.leer_ofertas_de_usuaria([O1, O2, O3, "basura"], ELLA)
    assert list(encontradas) == [_plano(O1)]


def test_the_batch_fetches_each_distinct_id_once(notion_falso):
    notion_falso["paginas"][_plano(O1)] = Respuesta(200, _pagina(O1))
    notion.leer_ofertas_de_usuaria([O1, _plano(O1), O1.upper()], ELLA)
    assert len(notion_falso["llamadas"]) == 1


def test_one_notion_failure_fails_the_whole_batch(notion_falso):
    notion_falso["paginas"][_plano(O1)] = Respuesta(200, _pagina(O1))
    notion_falso["paginas"][_plano(O2)] = Respuesta(500, {})
    with pytest.raises(notion.ErrorDeNotion):
        notion.leer_ofertas_de_usuaria([O1, O2], ELLA)


def test_the_batch_is_bounded_in_parallelism():
    assert 1 <= notion.MAX_HILOS_NOTION <= 3


def test_an_empty_batch_still_fails_closed_when_notion_is_unconfigured(notion_falso, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DB_OFERTAS", "")
    with pytest.raises(notion.ErrorDeNotion):
        notion.leer_ofertas_de_usuaria([], ELLA)
