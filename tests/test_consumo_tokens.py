"""TDD - Cada generacion informa de cuantos tokens gasto.

Caso real (2oct2026): para abrir el sistema a otras usuarias, cada una paga su
propia clave (ADR-004). Hay que poder decirle cuanto le cuesta un CV o una carta.
Claude devuelve el consumo en cada respuesta (`usage`) y cv-server lo tiraba:
se quedaba con el texto y nada mas.

Se guarda el dato, no el precio. El precio cambia y vive en la web del
proveedor; los tokens son lo que de verdad paso.
"""
from types import SimpleNamespace

import llm
import server as srv
from api import GenerarCVResponse


def _respuesta_anthropic(texto, entrada, salida):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=texto)],
        usage=SimpleNamespace(input_tokens=entrada, output_tokens=salida),
    )


class _ClienteFalso:
    def __init__(self, respuesta):
        self.messages = SimpleNamespace(create=lambda **k: respuesta)


def test_call_claude_conserva_el_texto(monkeypatch):
    monkeypatch.setattr(llm, "_anthropic_client", _ClienteFalso(_respuesta_anthropic("hola", 7600, 1200)))
    assert llm.call_claude("p", model="m") == "hola"


def test_la_capa_de_calidad_devuelve_los_tokens(monkeypatch):
    monkeypatch.setattr(llm, "_anthropic_client", _ClienteFalso(_respuesta_anthropic("cv", 7600, 1200)))
    r = llm.call_llm_calidad("p", model="claude-haiku-4-5")
    assert r.contenido == "cv"
    assert r.tokens_entrada == 7600
    assert r.tokens_salida == 1200


def test_sin_dato_de_consumo_los_tokens_quedan_vacios(monkeypatch):
    # Un proveedor o un doble de test que no informa: None, nunca un cero inventado.
    monkeypatch.setattr(llm, "call_claude", lambda *a, **k: "texto")
    r = llm.call_llm_calidad("p", model="claude-haiku-4-5")
    assert r.tokens_entrada is None and r.tokens_salida is None


def test_respuesta_llm_sigue_construyendose_con_dos_campos():
    r = srv.RespuestaLLM("texto", "modelo")
    assert r.tokens_entrada is None


def test_consumo_de_una_respuesta():
    r = srv.RespuestaLLM("t", "claude-haiku-4-5", 7600, 1200)
    assert srv.consumo_de(r) == {
        "modelo": "claude-haiku-4-5", "tokens_entrada": 7600, "tokens_salida": 1200,
    }


def test_la_api_no_filtra_el_consumo():
    # `response_model` descarta lo que no esta declarado: sin el campo, el dato
    # se calcula y no llega nunca a quien llama.
    assert "consumo" in GenerarCVResponse.model_fields
