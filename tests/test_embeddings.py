"""embeddings.py: Gemini embeddings client. No network: `requests.post` is faked."""
import math

import pytest

import embeddings


class _Respuesta:
    def __init__(self, datos):
        self._datos = datos

    def raise_for_status(self):
        pass

    def json(self):
        return self._datos


def _falso(monkeypatch, dim=3, valor=lambda texto: [3.0, 4.0, 0.0]):
    """Fake `requests.post`; returns the list where every call body is recorded."""
    llamadas = []

    def post(url, headers, json, timeout):
        llamadas.append({"url": url, "headers": headers, "json": json})
        return _Respuesta({"embeddings": [
            {"values": valor(r["content"]["parts"][0]["text"])} for r in json["requests"]]})

    monkeypatch.setattr(embeddings.requests, "post", post)
    return llamadas


def test_constantes():
    assert embeddings.DIMENSIONES == 768
    assert embeddings.MODELO == "gemini-embedding-001"


def test_lotes_de_cien(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-falsa")
    llamadas = _falso(monkeypatch)

    vectores = embeddings.embeddings([str(i) for i in range(150)])

    assert [len(c["json"]["requests"]) for c in llamadas] == [100, 50]
    assert len(vectores) == 150


def test_orden_se_conserva_entre_lotes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-falsa")
    _falso(monkeypatch, valor=lambda t: [1.0, float(t)])

    vectores = embeddings.embeddings([str(i) for i in range(150)])

    ys = [v[1] for v in vectores]
    assert ys == sorted(ys)  # monotonic in i after normalization


def test_cada_peticion_pide_768_dimensiones_y_similitud_semantica(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-falsa")
    llamadas = _falso(monkeypatch)

    embeddings.embeddings(["hola", "adios"])

    assert llamadas[0]["url"].endswith("gemini-embedding-001:batchEmbedContents")
    assert llamadas[0]["headers"] == {"x-goog-api-key": "clave-falsa"}
    for r in llamadas[0]["json"]["requests"]:
        assert r["outputDimensionality"] == 768
        assert r["taskType"] == "SEMANTIC_SIMILARITY"
        assert r["model"] == "models/gemini-embedding-001"


def test_los_vectores_se_devuelven_normalizados(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-falsa")
    _falso(monkeypatch, valor=lambda t: [3.0, 4.0, 0.0])

    [v] = embeddings.embeddings(["hola"])

    assert v == pytest.approx([0.6, 0.8, 0.0])
    assert math.sqrt(sum(x * x for x in v)) == pytest.approx(1.0)


def test_vector_nulo_no_revienta(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-falsa")
    _falso(monkeypatch, valor=lambda t: [0.0, 0.0])
    assert embeddings.embeddings(["x"]) == [[0.0, 0.0]]


def test_sin_textos_no_llama_a_gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert embeddings.embeddings([]) == []


def test_sin_clave_da_error_claro_no_systemexit(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        embeddings.embeddings(["hola"])


def test_se_importa_sin_credenciales_ni_red():
    # The shared subprocess check lives in test_modulos_sin_entorno (module is listed there).
    assert not hasattr(embeddings, "GEMINI_API_KEY")
