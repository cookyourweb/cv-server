"""scripts/experimento_embeddings.py: rank offers by meaning against a profile.

No network: Notion and Gemini are replaced with fakes of `requests.post`.
"""
import importlib.util
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parent.parent / "scripts" / "experimento_embeddings.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("experimento_embeddings", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def exp():
    return _cargar()


class _Respuesta:
    def __init__(self, datos):
        self._datos = datos

    def raise_for_status(self):
        pass

    def json(self):
        return self._datos


# ─── Import ─────────────────────────────────────────────────────────────────

def test_se_importa_sin_credenciales(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _cargar()  # must not raise KeyError


# ─── Cosine similarity ──────────────────────────────────────────────────────

def test_coseno_mismo_vector_es_uno(exp):
    assert exp.coseno([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_coseno_perpendiculares_es_cero(exp):
    assert exp.coseno([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_coseno_opuestos_es_menos_uno(exp):
    assert exp.coseno([1.0, 2.0], [-1.0, -2.0]) == pytest.approx(-1.0)


def test_coseno_no_depende_de_la_longitud(exp):
    assert exp.coseno([1.0, 1.0], [10.0, 10.0]) == pytest.approx(1.0)


# ─── Notion text ────────────────────────────────────────────────────────────

def test_texto_de_title_y_rich_text(exp):
    assert exp._texto({"title": [{"plain_text": "Acme"}]}) == "Acme"
    assert exp._texto({"rich_text": [{"plain_text": "Dev "}, {"plain_text": "React"}]}) == "Dev React"


def test_texto_de_propiedad_ausente_es_vacio(exp):
    assert exp._texto(None) == ""
    assert exp._texto({"rich_text": []}) == ""


# ─── Scoring ────────────────────────────────────────────────────────────────

def test_puntuar_resta_lo_que_evito_y_ordena(exp):
    ofertas = [{"empresa": "Java Corp"}, {"empresa": "React SL"}]
    perfil, anti = [1.0, 0.0], [0.0, 1.0]
    vectores = [[0.2, 1.0], [1.0, 0.1]]  # Java Corp is close to "evito"

    ranking = exp.puntuar(ofertas, perfil, anti, vectores)

    assert [o["empresa"] for o in ranking] == ["React SL", "Java Corp"]
    assert ranking[0]["score"] == pytest.approx(ranking[0]["quiero"] - ranking[0]["evito"])
    assert ranking[0]["score"] > 0 > ranking[1]["score"]


def test_puntuar_no_modifica_la_lista_original(exp):
    ofertas = [{"empresa": "A"}, {"empresa": "B"}]
    exp.puntuar(ofertas, [1.0, 0.0], [0.0, 1.0], [[0.0, 1.0], [1.0, 0.0]])
    assert ofertas == [{"empresa": "A"}, {"empresa": "B"}]


# ─── Duplicates ─────────────────────────────────────────────────────────────

def test_duplicados_solo_por_encima_del_umbral(exp):
    ofertas = [{"empresa": "A"}, {"empresa": "A bis"}, {"empresa": "B"}]
    vectores = [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]

    pares = exp.duplicados(ofertas, vectores, umbral=0.95)

    assert [(a["empresa"], b["empresa"]) for a, b, _ in pares] == [("A", "A bis")]


# ─── Gemini embeddings ──────────────────────────────────────────────────────

def test_embeddings_en_lotes_de_cien_y_en_orden(exp, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-falsa")
    llamadas = []

    def falso_post(url, headers, json, timeout):
        llamadas.append(len(json["requests"]))
        return _Respuesta({"embeddings": [
            {"values": [float(r["content"]["parts"][0]["text"])]} for r in json["requests"]]})

    monkeypatch.setattr(exp.requests, "post", falso_post)

    vectores = exp.embeddings([str(i) for i in range(150)])

    assert llamadas == [100, 50]
    assert vectores == [[float(i)] for i in range(150)]


def test_embeddings_sin_clave_da_error_claro(exp, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        exp.embeddings(["hola"])


# ─── Notion offers ──────────────────────────────────────────────────────────

def _pagina(empresa, puesto, descripcion="", estado="Pendiente"):
    return {"properties": {
        "Empresa": {"title": [{"plain_text": empresa}]},
        "Puesto": {"rich_text": [{"plain_text": puesto}]},
        "Descripción": {"rich_text": [{"plain_text": descripcion}]},
        "Notas": {"rich_text": []},
        "Estado": {"select": {"name": estado}},
    }}


def test_leer_ofertas_pagina_y_arma_el_texto(exp, monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "token-falso")
    cuerpos = []
    respuestas = [
        {"results": [_pagina("Acme", "Dev React", "Remoto")], "has_more": True, "next_cursor": "c2"},
        {"results": [_pagina("Beta", "AI Engineer")], "has_more": False},
    ]

    def falso_post(url, headers, json, timeout):
        cuerpos.append(json)
        return _Respuesta(respuestas[len(cuerpos) - 1])

    monkeypatch.setattr(exp.requests, "post", falso_post)

    ofertas = exp.leer_ofertas(["Pendiente"])

    assert [o["empresa"] for o in ofertas] == ["Acme", "Beta"]
    assert ofertas[0]["texto"].startswith("Dev React en Acme. Remoto")
    assert cuerpos[1]["start_cursor"] == "c2"
    assert cuerpos[0]["filter"] == {"or": [{"property": "Estado", "select": {"equals": "Pendiente"}}]}


def test_leer_ofertas_sin_token_da_error_claro(exp, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="NOTION_TOKEN"):
        exp.leer_ofertas(["Pendiente"])
