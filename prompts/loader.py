"""Carga de prompts versionados (LLMOps). Fallback a constantes hardcodeadas."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = os.getenv("PROMPT_VERSION", "v1")


def cargar_prompt(nombre: str, version: str = VERSION) -> str | None:
    """Lee prompts/<version>/<nombre>.txt si existe; None si no."""
    ruta = ROOT / version / f"{nombre}.txt"
    if ruta.exists():
        return ruta.read_text(encoding="utf-8")
    return None
