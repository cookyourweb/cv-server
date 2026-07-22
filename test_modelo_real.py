"""TDD - el modelo reportado tiene que ser el que se usó DE VERDAD.

Bug: /generar-cv devolvía `modelo_usado: GROQ_MODEL` hardcodeado aunque
`call_llm_calidad` hubiese respondido con Claude (o al revés). Sin esto no
se puede saber si Claude está funcionando en Render.
"""
from unittest.mock import patch

import cv_server_railway as srv


def test_call_llm_calidad_reporta_claude_cuando_claude_responde():
    with patch.object(srv, "call_claude", return_value="texto"):
        r = srv.call_llm_calidad("prompt", model="claude-haiku-4-5")
    assert r.contenido == "texto"
    assert r.modelo == "claude-haiku-4-5"


def test_call_llm_calidad_reporta_groq_cuando_claude_falla():
    with patch.object(srv, "call_claude", side_effect=RuntimeError("sin key")), \
         patch.object(srv, "call_llm", return_value=srv.RespuestaLLM("texto", "llama-3.3-70b-versatile")):
        r = srv.call_llm_calidad("prompt", model="claude-haiku-4-5")
    assert r.contenido == "texto"
    assert r.modelo == "llama-3.3-70b-versatile"


def test_call_llm_reporta_groq_cuando_groq_responde():
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    with patch.object(srv.requests, "post", return_value=_Resp()):
        r = srv.call_llm("prompt")
    assert r.contenido == "ok"
    assert r.modelo == srv.GROQ_MODEL


def test_call_llm_reporta_claude_cuando_groq_y_gemini_fallan(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"text": "ok claude"}]}

    monkeypatch.setattr(srv, "GEMINI_API_KEY", "")
    monkeypatch.setattr(srv, "CLAUDE_API_KEY", "k")

    llamadas = {"n": 0}

    def _post(url, **kw):
        llamadas["n"] += 1
        if "groq.com" in url:
            raise RuntimeError("groq caído")
        return _Resp()

    monkeypatch.setattr(srv.requests, "post", _post)
    r = srv.call_llm("prompt")
    assert r.contenido == "ok claude"
    assert r.modelo == srv.CLAUDE_MODEL
