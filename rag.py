"""RAG mínimo sobre el CV master: chunking + embeddings + retrieval + respuesta con citas.

Solo lectura. No modifica Notion ni Drive. Fail-closed ante errores.
"""
import logging
import os
import re

import llm
from embeddings import embeddings as embed
from errores import CVError

logger = logging.getLogger(__name__)

TAMANO_CHUNK = 500
SOLAPE = 80
TOP_K = 4


def chunkear(texto: str, tamano: int = TAMANO_CHUNK, solape: int = SOLAPE) -> list[str]:
    """Divide texto en trozos de ~tamano chars con solape. Por párrafos primero."""
    if not texto or not texto.strip():
        return []
    trozos = []
    # Primero por párrafos
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    actual = ""
    for p in parrafos:
        if len(actual) + len(p) + 2 <= tamano:
            actual = (actual + "\n\n" + p).strip() if actual else p
        else:
            if actual:
                trozos.append(actual)
            # Si un párrafo es más grande que tamano, partirlo por frases
            if len(p) > tamano:
                for i in range(0, len(p), tamano - solape):
                    trozos.append(p[i:i + tamano])
                actual = ""
            else:
                actual = p
    if actual:
        trozos.append(actual)
    # Solape: añadir los últimos chars del trozo anterior al siguiente
    if solape > 0 and len(trozos) > 1:
        solapados = [trozos[0]]
        for i in range(1, len(trozos)):
            prev = trozos[i - 1]
            solapados.append(prev[-solape:] + " " + trozos[i])
        trozos = solapados
    return trozos


def recuperar(pregunta: str, chunks: list[str], vectores_chunks: list[list[float]]) -> list[tuple[int, str, float]]:
    """Devuelve los top-k chunks más similares a la pregunta como (idx, texto, similitud)."""
    if not chunks or not vectores_chunks:
        return []
    vq = embed([pregunta])[0]
    # similitud coseno (vectores ya normalizados)
    sims = []
    for i, vc in enumerate(vectores_chunks):
        sim = sum(a * b for a, b in zip(vq, vc))
        sims.append((i, chunks[i], sim))
    sims.sort(key=lambda x: x[2], reverse=True)
    return sims[:TOP_K]


def responder(pregunta: str, chunks_recuperados: list[tuple[int, str, float]]) -> dict:
    """Llama al LLM con los chunks recuperados y pide respuesta con citas [1],[2],..."""
    if not chunks_recuperados:
        return {"respuesta": "No encontré información relevante en tu CV.", "citas": []}
    contexto = "\n\n".join(f"[{i+1}] {c[1]}" for i, c in enumerate(chunks_recuperados))
    prompt = (
        "Responde la pregunta del usuario usando SOLO la información de los fragmentos de CV "
        "proporcionados. Cita cada afirmación con [n] donde n es el número del fragmento. "
        "Si no hay información suficiente, dilo. No inventes datos.\n\n"
        f"FRAGMENTOS:\n{contexto}\n\n"
        f"PREGUNTA: {pregunta}\n\n"
        "RESPUESTA (con citas [n]):"
    )
    try:
        r = llm.call_llm(prompt)
        respuesta = r.contenido
    except Exception as e:
        logger.warning("rag: LLM falló: %s", type(e).__name__)
        raise CVError(503, "servicio no disponible")
    citas = [{"indice": c[0], "texto": c[1][:160], "similitud": round(c[2], 3)} for c in chunks_recuperados]
    return {"respuesta": respuesta, "citas": citas}


def preguntar_cv(email: str, pregunta: str, cv_texto: str) -> dict:
    """Pipeline completo: chunk → embed → retrieve → answer. Lanza CVError en errores."""
    if not pregunta or not pregunta.strip():
        raise CVError(400, "pregunta requerida")
    if not cv_texto or not cv_texto.strip():
        raise CVError(404, "no hay CV master")
    chunks = chunkear(cv_texto)
    if not chunks:
        raise CVError(404, "no hay CV master")
    try:
        vecs = embed(chunks)
    except Exception as e:
        logger.warning("rag: embeddings fallaron: %s", type(e).__name__)
        raise CVError(503, "servicio no disponible")
    recuperados = recuperar(pregunta, chunks, vecs)
    return responder(pregunta, recuperados)

