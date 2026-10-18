"""Gemini embeddings client: text -> unit-length vector of DIMENSIONES numbers.

The key is read on use (not on import) so the module imports without environment.
A missing key raises RuntimeError, like `llm.py`; this is a library, not a script.
"""
import math
import os

import requests

MODELO = "gemini-embedding-001"
# pgvector's HNSW index supports at most 2000 dimensions; 768 also uses less storage.
DIMENSIONES = 768
TAMANO_LOTE = 100


def _normalizar(v: list[float]) -> list[float]:
    """Gemini does NOT normalize vectors with reduced dimensionality; we do."""
    norma = math.sqrt(sum(x * x for x in v))
    return [x / norma for x in v] if norma else list(v)


def embeddings(textos: list[str]) -> list[list[float]]:
    """One call to Gemini turns up to 100 texts into vectors; order is preserved."""
    if not textos:
        return []
    clave = os.getenv("GEMINI_API_KEY", "")
    if not clave:
        raise RuntimeError("GEMINI_API_KEY no configurada")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:batchEmbedContents"
    vectores = []
    for i in range(0, len(textos), TAMANO_LOTE):
        lote = textos[i:i + TAMANO_LOTE]
        cuerpo = {"requests": [{"model": f"models/{MODELO}",
                                "content": {"parts": [{"text": t}]},
                                "taskType": "SEMANTIC_SIMILARITY",
                                "outputDimensionality": DIMENSIONES} for t in lote]}
        r = requests.post(url, headers={"x-goog-api-key": clave}, json=cuerpo, timeout=60)
        r.raise_for_status()
        vectores += [_normalizar(e["values"]) for e in r.json()["embeddings"]]
    return vectores
