"""La capa de CALIDAD es la que escribe el CV y la carta que van a una empresa.

Historia de por que existe este test:
- 28-ago-2026: al partir `cv_server_railway.py` en modulos, `llm.py` se llevo
  `get_anthropic_client()` pero NO se llevo el `import anthropic`. La linea
  `anthropic.Anthropic(...)` lanzaba `NameError`.
- El fallo era INVISIBLE: `call_llm_calidad` capturaba `Exception` a secas, se
  tragaba el `NameError` y caia a Groq. La funcion devolvia texto, los 191 tests
  seguian en verde, y cada CV enviado lo escribia Groq creyendo que era Claude.

Dos lecciones, un test por cada una:
1. El cliente de Anthropic tiene que poder construirse de verdad.
2. Un error de PROGRAMACION nuestro no es una caida del proveedor. La cadena de
   fallback existe para cuando Anthropic esta caido o sin cuota, no para tapar
   un bug del codigo. Si se degrada en silencio, no se entera nadie.
"""
import pytest

import llm


def test_get_anthropic_client_construye_el_cliente(monkeypatch):
    """Si falta el import, esto revienta con NameError en vez de dar un cliente."""
    monkeypatch.setattr(llm, "CLAUDE_API_KEY", "sk-ant-de-mentira")
    monkeypatch.setattr(llm, "_anthropic_client", None)

    cliente = llm.get_anthropic_client()

    assert cliente is not None


def test_call_llm_calidad_no_enmascara_un_error_de_programacion(monkeypatch):
    """Un NameError es un bug nuestro, no un proveedor caido: tiene que salir."""
    def revienta_como_un_bug(*args, **kwargs):
        raise NameError("name 'anthropic' is not defined")

    fallbacks_usados = []

    def fallback_espia(prompt):
        fallbacks_usados.append(prompt)
        return llm.RespuestaLLM("escrito por Groq", "groq")

    monkeypatch.setattr(llm, "call_claude", revienta_como_un_bug)
    monkeypatch.setattr(llm, "call_llm", fallback_espia)

    with pytest.raises(NameError):
        llm.call_llm_calidad("escribe el CV para esta oferta")

    assert fallbacks_usados == [], (
        "un bug del codigo se degrado a Groq en silencio: el CV lo escribio "
        "el fallback y nadie se entero"
    )


def test_call_llm_calidad_si_cae_a_groq_cuando_el_proveedor_falla(monkeypatch):
    """La red de seguridad sigue existiendo para lo que si es una caida real."""
    def proveedor_caido(*args, **kwargs):
        raise ConnectionError("Anthropic no responde")

    monkeypatch.setattr(llm, "call_claude", proveedor_caido)
    monkeypatch.setattr(
        llm, "call_llm", lambda p: llm.RespuestaLLM("escrito por Groq", "groq")
    )

    respuesta = llm.call_llm_calidad("escribe el CV para esta oferta")

    assert respuesta.modelo == "groq"
