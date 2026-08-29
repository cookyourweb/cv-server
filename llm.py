"""Capa LLM: quien escribe cada documento y en que orden se cae.

DOS cadenas, y confundirlas ha costado tiempo antes:

- `call_llm`: Groq primario, luego Gemini, luego Claude. Uso general.
- `call_llm_calidad`: **Claude primario**, con Groq de fallback. Es la que escribe
  el CV y la carta, o sea lo que sale hacia las empresas.

Los modelos se retiran sin avisar y la cadena de fallback casi nunca se ejercita,
asi que puede llevar meses muerta sin que nadie lo note. Por eso los defaults de
aqui estan cubiertos por `tests/test_modelos_retirados.py`.

Lee sus credenciales del entorno igual que el servidor: no importa nada de
`server`. Extraido el 28-ago-2026.
"""
import logging
import os
from typing import NamedTuple

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


def call_llm(prompt: str) -> RespuestaLLM:
    """Llama a Groq; si falla intenta Gemini y luego Claude."""

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
