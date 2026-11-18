"""Tests for rag.py (RAG with citations)."""
import unittest.mock as mock

import pytest

import rag


def test_chunkear_vacio():
    assert rag.chunkear("") == []
    assert rag.chunkear("   ") == []


def test_chunkear_un_parrafo():
    texto = "a" * 100
    chunks = rag.chunkear(texto, tamano=50, solape=0)
    assert len(chunks) >= 2
    assert all(len(c) <= 60 for c in chunks)


def test_chunkear_varios_parrafos():
    texto = "Parrafo uno.\n\nParrafo dos.\n\nParrafo tres."
    chunks = rag.chunkear(texto, tamano=200, solape=0)
    assert len(chunks) >= 1
    assert "Parrafo uno" in chunks[0]


def test_recuperar_top_k():
    chunks = ["chunk a", "chunk b", "chunk c"]
    vecs = [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]
    # pregunta similar a chunk a
    with mock.patch("rag.embed", return_value=[[1.0, 0.0]]):
        res = rag.recuperar("pregunta", chunks, vecs)
    assert len(res) == rag.TOP_K or len(res) == len(chunks)
    assert res[0][0] == 0  # chunk a es el más similar


def test_responder_sin_chunks():
    r = rag.responder("pregunta", [])
    assert "No encontré" in r["respuesta"]
    assert r["citas"] == []


@mock.patch("rag.llm.call_llm")
@mock.patch("rag.embed")
def test_preguntar_cv_ok(mock_embed, mock_llm):
    def fake_embed(textos):
        return [[0.1, 0.2] for _ in textos]
    mock_embed.side_effect = fake_embed
    mock_llm.return_value = type("R", (), {"contenido": "Respuesta con cita [1]."})()
    texto = "Parrafo uno sobre Angular.\n\nParrafo dos sobre React."
    r = rag.preguntar_cv("a@b.com", "que sabe de angular?", texto)
    assert "respuesta" in r
    assert "citas" in r
    assert len(r["citas"]) > 0


def test_preguntar_cv_pregunta_vacia():
    from errores import CVError
    with pytest.raises(CVError) as exc:
        rag.preguntar_cv("a@b.com", "", "texto")
    assert exc.value.status == 400


def test_preguntar_cv_sin_cv():
    from errores import CVError
    with pytest.raises(CVError) as exc:
        rag.preguntar_cv("a@b.com", "pregunta", "")
    assert exc.value.status == 404