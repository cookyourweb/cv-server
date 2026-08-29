"""Capa LLM: quien escribe cada documento, en que orden se cae y con que backend.

DOS cadenas, y confundirlas ha costado tiempo antes:

- `call_llm`: Groq primario, luego Gemini, luego Claude. Uso general.
- `call_llm_calidad`: **Claude primario**, con Groq de fallback. Es la que escribe
  el CV y la carta, o sea lo que sale hacia las empresas.

DOS backends para la primera, elegidos con `LLM_BACKEND`:

- `casera` (por defecto): tres llamadas con `requests`, cero dependencias extra.
- `litellm`: la libreria estandar del sector. Escrita y probada, APAGADA por
  defecto. Cuesta +146 MB de disco, +5,96 s de arranque y 207 MB de RAM frente a
  los 9 MB del proceso pelado. Se enciende el dia que el alojamiento lo aguante,
  sin tocar una linea. El porque esta medido en `docs/ADR-004-backend-llm.md`.

Los modelos se retiran sin avisar y la cadena de fallback casi nunca se ejercita,
asi que puede llevar meses muerta sin que nadie lo note. Por eso los defaults de
aqui estan cubiertos por `tests/test_modelos_retirados.py`.

Lee sus credenciales del entorno igual que el servidor: no importa nada de
`server`. Extraido el 28-ago-2026.
"""
import logging
import os
from typing import NamedTuple, Protocol

import anthropic
import requests

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

CV_MODEL = os.getenv("CV_MODEL", "claude-haiku-4-5")
CARTA_MODEL = os.getenv("CARTA_MODEL", "claude-sonnet-4-6")

class RespuestaLLM(NamedTuple):
    """Respuesta de un LLM junto al modelo que la generó DE VERDAD.

    Sin esto no se puede saber si el CV lo escribió Claude o el fallback
    de Groq: los endpoints reportaban el modelo configurado, no el usado.
    """
    contenido: str
    modelo:    str


class BackendLLM(Protocol):
    """Lo que cualquier backend de la cascada tiene que ofrecer. Nada mas.

    Un `Protocol` no se hereda: cualquier objeto con estos dos miembros vale.

    ═══ SI VAS A ESCRIBIR UN BACKEND NUEVO, LEE ESTO ═══

    La regla: **el sustituto puede prometer MAS, nunca menos.** Quien llama a
    `call_llm` no sabe cual le ha tocado, asi que todos tienen que comportarse
    igual ante la misma llamada.

    Las tres formas de romperlo:

    1. `modelo` es el que RESPONDIO, no el que estaba configurado. Si devuelves
       el configurado, se pierde la unica forma de saber quien escribio el CV.
    2. Si fallan todos, se lanza `RuntimeError`. No devuelvas `None` ni un
       `RespuestaLLM` con el contenido vacio: quien llama no lo comprueba.
    3. No cargues tu dependencia al importar el modulo. El backend apagado no
       puede costar ni un byte, que es justo el motivo de que haya dos.
    """
    nombre: str

    def completar(self, prompt: str) -> RespuestaLLM: ...


class CascadaCasera:
    """Groq, luego Gemini, luego Claude, a pelo con `requests`.

    Sesenta lineas y cero dependencias extra. Mientras el servicio sea pequeño,
    esto gana a cualquier libreria por pura economia.
    """
    nombre = "casera"

    def completar(self, prompt: str) -> RespuestaLLM:
        # ── 1. Groq ──────────────────────────────
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                },
                json={
                    "model":      GROQ_MODEL,
                    "messages":   [{"role": "user", "content": prompt}],
                    "max_tokens": 4096,
                    "temperature": 0.7,
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            logger.info("LLM: Groq OK (%s)", GROQ_MODEL)
            return RespuestaLLM(content, GROQ_MODEL)
        except Exception as e:
            logger.warning("Groq falló: %s — probando fallbacks", e)

        # ── 2. Gemini (fallback) ──────────────────
        if GEMINI_API_KEY:
            try:
                resp = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                    params={"key": GEMINI_API_KEY},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=30,
                )
                resp.raise_for_status()
                content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                logger.info("LLM: Gemini fallback OK (%s)", GEMINI_MODEL)
                return RespuestaLLM(content, GEMINI_MODEL)
            except Exception as e:
                logger.warning("Gemini fallback falló: %s — probando Claude", e)

        # ── 3. Claude (fallback) ──────────────────
        if CLAUDE_API_KEY:
            try:
                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "Content-Type":      "application/json",
                        "x-api-key":         CLAUDE_API_KEY,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model":      CLAUDE_MODEL,
                        "max_tokens": 4096,
                        "messages":   [{"role": "user", "content": prompt}],
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                content = resp.json()["content"][0]["text"]
                logger.info("LLM: Claude fallback OK (%s)", CLAUDE_MODEL)
                return RespuestaLLM(content, CLAUDE_MODEL)
            except Exception as e:
                logger.error("Claude fallback falló: %s", e)

        raise RuntimeError("Todos los LLMs fallaron. Revisa las API keys y el estado de los servicios.")


# Las variables de este proyecto NO se llaman como las que busca litellm. El caso
# real es Claude: aqui es `CLAUDE_API_KEY` desde el primer dia y litellm busca
# `ANTHROPIC_API_KEY`. Sin este mapeo el ULTIMO eslabon de la cascada esta muerto,
# y eso no se nota hasta el dia que caen los otros dos a la vez. Comprobado con
# llamadas reales el 29-ago-2026: sin mapear, `APIConnectionError`; mapeando,
# Claude contesto en 1,0 s.
NOMBRES_QUE_ESPERA_LITELLM = {"ANTHROPIC_API_KEY": "CLAUDE_API_KEY"}


def _alinear_credenciales_para_litellm() -> None:
    """Publica nuestras claves con el nombre que litellm sabe buscar.

    No pisa lo que ya hubiera en el entorno: si alguien define
    `ANTHROPIC_API_KEY` a mano, manda esa.
    """
    for espera_litellm, la_nuestra in NOMBRES_QUE_ESPERA_LITELLM.items():
        valor = globals().get(la_nuestra) or os.getenv(la_nuestra, "")
        if valor:
            # `setdefault` y no asignacion por indice: si alguien ya la definio a
            # mano, manda la suya. Ademas deja el modulo libre de accesos por
            # corchetes, que es lo que vigila tests/test_modulos_sin_entorno.py.
            os.environ.setdefault(espera_litellm, valor)


class CascadaLiteLLM:
    """La misma cascada, delegada en LiteLLM. APAGADA por defecto.

    Lo que gana frente a la casera: una sola llamada en vez de tres bloques
    escritos a mano, y los nombres de modelo normalizados por una libreria que
    sigue los cambios de los proveedores. El 28-ago-2026 se retiraron TRES
    modelos en un dia; esa es la clase de problema que LiteLLM absorbe.

    Lo que cuesta, medido: +146 MB de disco, +5,96 s de `import` y 207 MB de RAM.
    Por eso el `import` esta DENTRO del metodo. Mientras nadie encienda este
    backend, el proceso no paga nada. Ese contrato lo vigila
    `tests/test_backend_llm.py::test_importar_llm_no_carga_litellm`.
    """
    nombre = "litellm"

    def completar(self, prompt: str) -> RespuestaLLM:
        import litellm  # perezoso A PROPOSITO: ver el docstring de la clase

        _alinear_credenciales_para_litellm()

        resp = litellm.completion(
            model=f"groq/{GROQ_MODEL}",
            messages=[{"role": "user", "content": prompt}],
            fallbacks=[
                f"gemini/{GEMINI_MODEL}",
                f"anthropic/{CLAUDE_MODEL}",
            ],
            max_tokens=4096,
            temperature=0.7,
            timeout=30,
        )
        # `resp.model` es el que RESPONDIO, que con fallbacks no tiene por que
        # ser el primario. Mantiene el contrato de `RespuestaLLM`.
        return RespuestaLLM(resp.choices[0].message.content, resp.model)


BACKENDS: dict[str, type] = {
    CascadaCasera.nombre:  CascadaCasera,
    CascadaLiteLLM.nombre: CascadaLiteLLM,
}


def backend_activo() -> BackendLLM:
    """El backend que dice `LLM_BACKEND`, o la casera si no dice nada.

    Se lee en cada llamada, no al importar, para que un test pueda cambiarlo y
    para que en Render baste reiniciar el servicio.
    """
    nombre = os.getenv("LLM_BACKEND", CascadaCasera.nombre)
    try:
        return BACKENDS[nombre]()
    except KeyError:
        raise ValueError(
            f"LLM_BACKEND={nombre!r} no existe. Los que hay: "
            f"{', '.join(sorted(BACKENDS))}"
        ) from None


def call_llm(prompt: str) -> RespuestaLLM:
    """Puerta publica de la cascada. Quien llama no sabe que backend hay debajo."""
    return backend_activo().completar(prompt)


# ── Capa CALIDAD: Claude primario para el CV (lo que va a empresas) ──
_anthropic_client = None

def get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        if not CLAUDE_API_KEY:
            raise RuntimeError("CLAUDE_API_KEY no configurada")
        _anthropic_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    return _anthropic_client


def call_claude(prompt: str, model: str, max_tokens: int = 4096) -> str:
    """Llama a Claude vía SDK oficial. Para CV/carta donde la calidad importa."""
    resp = get_anthropic_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def call_llm_calidad(prompt: str, model: str = CV_MODEL, max_tokens: int = 4096) -> RespuestaLLM:
    """Claude primario; si falla (rate limit, red o sin key) cae a Groq.
    Para el CV y textos que van a una empresa — mejor que Groq, ~$0,02/CV."""
    try:
        contenido = call_claude(prompt, model=model, max_tokens=max_tokens)
        logger.info("LLM calidad: Claude OK (%s)", model)
        return RespuestaLLM(contenido, model)
    except (NameError, AttributeError, TypeError, ImportError):
        # Bug NUESTRO, no una caida del proveedor. Degradarlo a Groq lo esconde:
        # el 28-ago-2026 un `import` que falto dejo la capa de calidad muerta y
        # los CVs los escribio el fallback sin que nadie se enterase.
        raise
    except Exception as e:
        logger.warning("Claude falló (%s) — cayendo a Groq", e)
        return call_llm(prompt)
