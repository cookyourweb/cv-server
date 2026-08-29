"""La capa LLM tiene DOS backends y solo se paga el que se enciende.

Historia de por que existe esto:
- 29-ago-2026: se evaluo LiteLLM para sustituir la cascada escrita a mano.
  Medido en el venv: **+146 MB de disco, +5,96 s de `import` y 207 MB de RAM**
  frente a los 9 MB del proceso pelado. Para un servidor web pequeño no
  compensa hoy (ver `docs/ADR-004-backend-llm.md`).
- Decision: el adaptador se escribe, se prueba y se documenta AHORA, y se
  enciende el dia que el plan de alojamiento lo aguante. Cambiar de backend
  tiene que ser una variable de entorno, no un refactor.

El test que sostiene la decision entera es
`test_importar_llm_no_carga_litellm`: si alguien sube el `import litellm` al
principio del modulo, el arranque empieza a pagar los seis segundos y los
200 MB en silencio, exactamente el tipo de fallo que no se nota hasta que la
factura o el timeout lo cuentan.
"""
import subprocess
import sys
import types

import pytest

import llm


def test_backend_por_defecto_es_la_cascada_casera(monkeypatch):
    """Sin tocar nada, se sigue usando lo que ya funciona y no cuesta nada."""
    monkeypatch.delenv("LLM_BACKEND", raising=False)

    backend = llm.backend_activo()

    assert backend.nombre == "casera"


def test_backend_litellm_se_elige_con_una_variable_de_entorno(monkeypatch):
    """Encenderlo el dia de mañana no puede exigir tocar codigo."""
    monkeypatch.setenv("LLM_BACKEND", "litellm")

    backend = llm.backend_activo()

    assert backend.nombre == "litellm"


def test_backend_desconocido_falla_claro_y_pronto(monkeypatch):
    """Un typo en la variable no puede degradar en silencio a otro backend."""
    monkeypatch.setenv("LLM_BACKEND", "litelm")

    with pytest.raises(ValueError, match="litelm"):
        llm.backend_activo()


def test_importar_llm_no_carga_litellm():
    """EL TEST QUE PROTEGE LA FACTURA.

    `import llm` no puede arrastrar litellm. Se comprueba en un proceso limpio
    porque en esta misma suite otro test si lo carga a proposito, y entonces ya
    estaria en `sys.modules` y el test mentiria.
    """
    codigo = "import sys; import llm; print('litellm' in sys.modules)"

    salida = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        check=True,
    )

    assert salida.stdout.strip() == "False", (
        "importar `llm` ha cargado litellm: el arranque acaba de encarecerse "
        "6 segundos y 200 MB sin que nadie lo pidiera"
    )


def test_cascada_litellm_reporta_el_modelo_que_respondio_de_verdad(monkeypatch):
    """Mismo contrato que la casera: el modelo reportado es el que escribio.

    Se gano a pulso: los endpoints reportaban el modelo CONFIGURADO, no el
    usado, y no habia forma de saber si el CV lo escribio Claude o el fallback.
    """
    class _Mensaje:
        content = "texto del modelo"

    class _Choice:
        message = _Mensaje()

    class _Respuesta:
        choices = [_Choice()]
        model = "gemini/gemini-3.6-flash"   # respondio el fallback, no el primario

    llamadas = {}

    def _completion(**kwargs):
        llamadas.update(kwargs)
        return _Respuesta()

    falso_litellm = types.ModuleType("litellm")
    falso_litellm.completion = _completion
    monkeypatch.setitem(sys.modules, "litellm", falso_litellm)

    respuesta = llm.CascadaLiteLLM().completar("escribe algo")

    assert respuesta.contenido == "texto del modelo"
    assert respuesta.modelo == "gemini/gemini-3.6-flash"
    assert llamadas["fallbacks"], "sin fallbacks LiteLLM no aporta nada sobre requests"


def test_call_llm_delega_en_el_backend_activo(monkeypatch):
    """`call_llm` es la puerta publica: quien la llama no sabe que backend hay."""
    class _BackendDePrueba:
        nombre = "de-prueba"

        def completar(self, prompt):
            return llm.RespuestaLLM("respondio el backend", "modelo-de-prueba")

    monkeypatch.setattr(llm, "backend_activo", lambda: _BackendDePrueba())

    respuesta = llm.call_llm("prompt")

    assert respuesta.modelo == "modelo-de-prueba"
