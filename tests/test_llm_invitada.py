"""The generation chain for INVITED users: Claude, then Groq, and nothing else.

The consent text names only Anthropic and Groq, so an invited user's CV and cover letter must
never reach Gemini nor the general cascade (`call_llm`). Claude uses the GENERAL key
(`CLAUDE_API_KEY`); the extraction's dedicated key stays exclusive to the extraction.
No test calls the network: the SDK client and `requests.post` are fakes.
"""
from types import SimpleNamespace

import pytest

import llm

CLAVE_ALTA = "clave-alta-de-prueba"
CLAVE_GENERAL = "clave-general-de-prueba"


class AnthropicFalso:
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
    monkeypatch.setenv("ANTHROPIC_CLAVE_ALTA", CLAVE_ALTA)
    monkeypatch.setattr(llm, "CLAUDE_API_KEY", CLAVE_GENERAL)
    monkeypatch.setattr(llm, "GROQ_API_KEY", "groq-de-prueba")
    monkeypatch.setattr(llm, "GEMINI_API_KEY", "gemini-de-prueba")
    monkeypatch.setattr(llm, "_anthropic_client", None)

    def prohibida(*args, **kwargs):
        pytest.fail("the invited chain must never use the general cascade (Gemini)")
    monkeypatch.setattr(llm, "call_llm", prohibida)
    monkeypatch.setattr(llm.CascadaCasera, "completar", prohibida)
    monkeypatch.setattr(llm.CascadaLiteLLM, "completar", prohibida)


@pytest.fixture
def http(monkeypatch):
    llamadas = []

    def post(url, **kwargs):
        llamadas.append({"url": url, **kwargs})
        if "api.groq.com" not in url:
            pytest.fail(f"the invited chain must only talk to Groq over HTTP, not {url}")
        return RespuestaHttp({"choices": [{"message": {"content": "de groq"}}],
                              "usage": {"prompt_tokens": 21, "completion_tokens": 9}})
    monkeypatch.setattr(llm.requests, "post", post)
    return llamadas


def test_claude_answers_with_the_general_key_and_the_asked_limit(http):
    r = llm.call_llm_invitada("prompt", model="modelo-cv", max_tokens=1500)
    assert (r.contenido, r.modelo, r.tokens_entrada, r.tokens_salida) == ("de claude", "modelo-cv", 11, 7)
    (llamada,) = AnthropicFalso.llamadas
    assert llamada["model"] == "modelo-cv" and llamada["max_tokens"] == 1500
    (construido,) = AnthropicFalso.construidos
    assert construido["api_key"] == CLAVE_GENERAL != CLAVE_ALTA
    assert http == []


def test_when_claude_fails_groq_answers_with_the_asked_limit_and_never_gemini(http):
    AnthropicFalso.error = RuntimeError("claude caido")
    r = llm.call_llm_invitada("prompt", model="modelo-cv", max_tokens=4096)
    assert (r.contenido, r.modelo) == ("de groq", llm.GROQ_MODEL)
    (llamada,) = http
    assert llamada["json"]["max_tokens"] == 4096 and llamada["json"]["model"] == llm.GROQ_MODEL


def test_without_the_general_key_it_goes_straight_to_groq(http, monkeypatch):
    monkeypatch.setattr(llm, "CLAUDE_API_KEY", "")
    r = llm.call_llm_invitada("prompt", model="modelo-cv", max_tokens=4096)
    assert r.modelo == llm.GROQ_MODEL and AnthropicFalso.llamadas == []


def test_when_both_fail_it_raises_runtime_error_with_a_fixed_message_and_never_gemini(monkeypatch):
    AnthropicFalso.error = RuntimeError("claude caido")
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return RespuestaHttp({}, 500)
    monkeypatch.setattr(llm.requests, "post", post)
    with pytest.raises(RuntimeError, match="Todos los LLMs fallaron"):
        llm.call_llm_invitada("prompt", model="modelo-cv", max_tokens=4096)
    assert len(urls) == 1 and "api.groq.com" in urls[0]


def test_a_bug_of_ours_in_the_claude_step_is_not_hidden_by_the_fallback(http):
    AnthropicFalso.error = AttributeError("bug")
    with pytest.raises(AttributeError):
        llm.call_llm_invitada("prompt", model="modelo-cv", max_tokens=4096)
    assert http == []


def test_the_extraction_chain_is_unchanged_and_keeps_its_own_cap(http):
    r = llm.call_llm_extraccion("prompt", model="modelo-cv")
    assert r.contenido == "de claude"
    assert AnthropicFalso.llamadas[0]["max_tokens"] == llm.TOKENS_SALIDA_EXTRACCION == 1200
    assert AnthropicFalso.construidos[0]["api_key"] == CLAVE_ALTA
