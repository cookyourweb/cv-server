"""The provider chain of the owner-paid extraction: Claude, then Groq, and nothing else.

The consent text and the ADR-004 amendment name ONLY Anthropic and Groq, so this chain must
never reach Gemini nor the general cascade (`call_llm`). No test calls the network: the
Anthropic SDK client and `requests.post` are replaced by fakes.
"""
from types import SimpleNamespace

import pytest

import extraccion
import llm

CLAVE_ALTA = "clave-alta-de-prueba"


class AnthropicFalso:
    """Stands for `anthropic.Anthropic`: records its constructor kwargs and every create() call."""
    construidos: list = []
    llamadas: list = []
    error = None

    def __init__(self, **kwargs):
        type(self).construidos.append(kwargs)
        self.messages = SimpleNamespace(create=self._crear)

    def _crear(self, **kwargs):
        type(self).llamadas.append(kwargs)
        if type(self).error is not None:
            raise type(self).error
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="de claude")],
                               usage=SimpleNamespace(input_tokens=11, output_tokens=7))


class RespuestaHttp:
    def __init__(self, cuerpo, estado=200):
        self.cuerpo, self.status_code = cuerpo, estado

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http")

    def json(self):
        return self.cuerpo


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    AnthropicFalso.construidos, AnthropicFalso.llamadas, AnthropicFalso.error = [], [], None
    monkeypatch.setattr(llm.anthropic, "Anthropic", AnthropicFalso)
    monkeypatch.setattr(llm, "CLAUDE_API_KEY", CLAVE_ALTA)
    monkeypatch.setattr(llm, "GROQ_API_KEY", "groq-de-prueba")
    monkeypatch.setattr(llm, "GEMINI_API_KEY", "gemini-de-prueba")
    monkeypatch.setattr(llm, "_anthropic_client", None)


@pytest.fixture
def http(monkeypatch):
    """Every `requests.post`: recorded. Groq answers; anything else (Gemini, Claude over HTTP) fails the test."""
    llamadas = []

    def post(url, **kwargs):
        llamadas.append({"url": url, **kwargs})
        if "api.groq.com" not in url:
            pytest.fail(f"the extraction chain must only talk to Groq over HTTP, not {url}")
        return RespuestaHttp({"choices": [{"message": {"content": "de groq"}}],
                              "usage": {"prompt_tokens": 21, "completion_tokens": 9}})
    monkeypatch.setattr(llm.requests, "post", post)
    return llamadas


@pytest.fixture(autouse=True)
def sin_cascada_general(monkeypatch):
    def prohibida(*args, **kwargs):
        pytest.fail("the extraction chain must never use the general cascade")
    monkeypatch.setattr(llm, "call_llm", prohibida)
    monkeypatch.setattr(llm.CascadaCasera, "completar", prohibida)
    monkeypatch.setattr(llm.CascadaLiteLLM, "completar", prohibida)


def test_the_cap_is_one_constant_shared_with_the_cost_estimate():
    assert llm.TOKENS_SALIDA_EXTRACCION == 1200
    assert extraccion.TOKENS_SALIDA_MAX is llm.TOKENS_SALIDA_EXTRACCION


def test_claude_answers_with_the_cap_and_its_real_usage(http):
    r = llm.call_llm_extraccion("prompt", model="modelo-cv")
    assert (r.contenido, r.modelo, r.tokens_entrada, r.tokens_salida) == ("de claude", "modelo-cv", 11, 7)
    (llamada,) = AnthropicFalso.llamadas
    assert llamada["model"] == "modelo-cv" and llamada["max_tokens"] == 1200
    assert http == []


def test_when_claude_fails_groq_answers_with_the_cap_and_never_gemini(http):
    AnthropicFalso.error = RuntimeError("claude caido")
    r = llm.call_llm_extraccion("prompt", model="modelo-cv")
    assert (r.contenido, r.modelo) == ("de groq", llm.GROQ_MODEL)
    assert (r.tokens_entrada, r.tokens_salida) == (21, 9)
    (llamada,) = http
    assert "api.groq.com" in llamada["url"] and llamada["json"]["max_tokens"] == 1200
    assert llamada["json"]["model"] == llm.GROQ_MODEL


def test_groq_without_usage_reports_none_never_a_made_up_zero(http, monkeypatch):
    AnthropicFalso.error = RuntimeError("claude caido")
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, **k: RespuestaHttp({"choices": [{"message": {"content": "de groq"}}]}))
    r = llm.call_llm_extraccion("prompt", model="modelo-cv")
    assert r.tokens_entrada is None and r.tokens_salida is None


def test_when_both_fail_it_raises_and_gemini_is_never_called(monkeypatch):
    AnthropicFalso.error = RuntimeError("claude caido")
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return RespuestaHttp({}, 500)
    monkeypatch.setattr(llm.requests, "post", post)
    with pytest.raises(RuntimeError):
        llm.call_llm_extraccion("prompt", model="modelo-cv")
    assert len(urls) == 1 and "api.groq.com" in urls[0]


def test_a_bug_of_ours_in_the_claude_step_is_not_hidden_by_the_fallback(http):
    AnthropicFalso.error = AttributeError("bug")
    with pytest.raises(AttributeError):
        llm.call_llm_extraccion("prompt", model="modelo-cv")
    assert http == []
