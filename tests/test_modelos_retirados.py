"""Canario: ningun modelo por defecto puede ser uno que el proveedor ya retiro.

Historia de por que existe este test:
- 19-abr-2026: Anthropic retiro `claude-3-haiku-20240307`. El default de CLAUDE_MODEL
  se quedo apuntando ahi y la cadena de fallback devolvia 404 sin que nadie lo notase,
  porque casi nunca se ejercita.
- 16-ago-2026: Groq retiro `llama-3.3-70b-versatile`. El buscador de ofertas estuvo
  10 dias sin traer una sola oferta y el correo de error culpaba a la memoria.

El fallo es SILENCIOSO: el default solo se usa cuando falta la variable de entorno,
asi que en Render sigue funcionando mientras en local arranca roto. Este test fija
la lista de modelos retirados y revienta si alguno vuelve a colarse como default.

Al retirar un modelo nuevo: anadirlo a MODELOS_RETIRADOS con su fecha.
"""
import server as srv
import real_jobs

MODELOS_RETIRADOS = {
    "llama-3.3-70b-versatile": "Groq, 16-ago-2026",
    "claude-3-haiku-20240307": "Anthropic, 19-abr-2026",
    # Los dos, comprobados contra la API el 28-ago-2026: 404. Google responde
    # "no longer available, please update to models/gemini-3.6-flash".
    "gemini-1.5-flash": "Google, retirado antes del 28-ago-2026",
    "gemini-2.0-flash": "Google, retirado antes del 28-ago-2026",
}


def _defaults():
    return {
        "server.GROQ_MODEL": srv.GROQ_MODEL,
        "server.CLAUDE_MODEL": srv.CLAUDE_MODEL,
        "server.CV_MODEL": srv.CV_MODEL,
        "server.CARTA_MODEL": srv.CARTA_MODEL,
        "server.GEMINI_MODEL": srv.GEMINI_MODEL,
        "real_jobs.GROQ_MODEL_DEFAULT": real_jobs.GROQ_MODEL_DEFAULT,
    }


def test_ningun_default_apunta_a_un_modelo_retirado():
    muertos = {
        nombre: f"{modelo} (retirado por {MODELOS_RETIRADOS[modelo]})"
        for nombre, modelo in _defaults().items()
        if modelo in MODELOS_RETIRADOS
    }
    assert not muertos, f"Defaults apuntando a modelos retirados: {muertos}"


# ─────────────────────────────────────────────────────────────────────────────
# El canario de arriba vigila los DEFAULTS DEL CODIGO. No basta.
#
# 29-ago-2026: probando la cascada de LiteLLM con llamadas reales, el ultimo
# eslabon devolvia 404. La causa: `.env` tenia CLAUDE_MODEL=claude-3-haiku-20240307,
# **un modelo de la lista de arriba, retirado el 19-abr-2026**. El default del
# codigo estaba bien; lo que apuntaba al muerto era el entorno, que es el que manda.
#
# O sea: el canario cantaba en la jaula equivocada. Este mira el `.env` de verdad.
# ─────────────────────────────────────────────────────────────────────────────
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

VARIABLES_DE_MODELO = (
    "GROQ_MODEL", "GEMINI_MODEL", "CLAUDE_MODEL", "CV_MODEL", "CARTA_MODEL",
)


def _modelos_declarados_en(fichero: Path) -> dict:
    if not fichero.exists():
        return {}
    declarados = {}
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        if clave in VARIABLES_DE_MODELO:
            declarados[clave] = valor.strip().strip('"').strip("'")
    return declarados


def test_el_env_local_no_apunta_a_un_modelo_retirado():
    """Si existe `.env`, sus modelos tambien tienen que estar vivos.

    Se salta si no hay `.env` (en CI no lo hay), porque su ausencia no es un
    fallo: lo que se vigila es que quien SI lo tenga no arrastre un modelo muerto.
    """
    env = RAIZ / ".env"
    if not env.exists():
        pytest.skip("no hay .env local que revisar")

    muertos = {
        clave: f"{modelo} (retirado por {MODELOS_RETIRADOS[modelo]})"
        for clave, modelo in _modelos_declarados_en(env).items()
        if modelo in MODELOS_RETIRADOS
    }
    assert not muertos, (
        f".env apunta a modelos retirados: {muertos}. "
        "El default del codigo esta bien, pero manda el entorno."
    )


def test_el_env_example_no_apunta_a_un_modelo_retirado():
    """`.env.example` es lo que copia quien monta el proyecto de cero.

    Un modelo muerto ahi se propaga a cada instalacion nueva.
    """
    muertos = {
        clave: f"{modelo} (retirado por {MODELOS_RETIRADOS[modelo]})"
        for clave, modelo in _modelos_declarados_en(RAIZ / ".env.example").items()
        if modelo in MODELOS_RETIRADOS
    }
    assert not muertos, f".env.example apunta a modelos retirados: {muertos}"
