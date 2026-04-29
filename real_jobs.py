#!/usr/bin/env python3
"""
real_jobs.py — Búsqueda de ofertas REALES (sustituye al LLM inventando ofertas)

Fase 1: Integración con Remotive API (https://remotive.com/api-documentation)
- Sin API key
- Sin rate limits estrictos (recomendación: max 4 req/día por término)
- Solo ofertas remotas

Funciones públicas:
    buscar_ofertas_reales(perfil_usuario) → list[dict]   # función orquestadora
    buscar_remotive(rol, max_results)     → list[dict]   # llamada raw a Remotive
    rankear_con_groq(ofertas, perfil, ...) → list[dict]  # ranking con LLM

Schema de oferta normalizada (devuelta por estas funciones):
    {
        "id":              "remotive-2089995",        # source-id único
        "source":          "remotive",                # de qué fuente viene
        "empresa":         "Lemon.io",
        "puesto":          "Head of Engineering",
        "descripcion":     "..." (texto plano, máx 1000 chars),
        "tags":            ["AI/ML", "startup", ...],
        "modalidad":       "Remoto",                  # siempre "Remoto" en Remotive
        "ubicacion":       "USA timezones, European timezones",
        "salario":         "$120k - $150k" o "" si vacío,
        "tipo_contrato":   "full_time" | "part_time" | "freelance" | "contract",
        "link":            "https://remotive.com/...",
        "fecha_publicacion": "2026-04-24",
        "logo_empresa":    "https://...",
        # Añadidos por rankear_con_groq():
        "score":           87,                        # 0-100
        "motivo":          "Encaja por React + remoto + senior"
    }
"""

import os
import re
import json
import logging
import requests
from html import unescape

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
REMOTIVE_TIMEOUT = 15  # segundos

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"
GROQ_TIMEOUT = 30


# ══════════════════════════════════════════════
# UTILIDADES — limpieza y normalización
# ══════════════════════════════════════════════

def limpiar_html(texto: str, max_chars: int = 1000) -> str:
    """Elimina tags HTML, entidades y espacios redundantes. Trunca a max_chars."""
    if not texto:
        return ""
    # Quitar tags HTML
    sin_tags = re.sub(r"<[^>]+>", " ", texto)
    # Decodificar entidades HTML (&amp; etc.)
    decodificado = unescape(sin_tags)
    # Colapsar espacios y newlines
    limpio = re.sub(r"\s+", " ", decodificado).strip()
    # Truncar
    if len(limpio) > max_chars:
        limpio = limpio[:max_chars].rsplit(" ", 1)[0] + "…"
    return limpio


def normalizar_oferta_remotive(raw: dict) -> dict:
    """Convierte el JSON crudo de Remotive a nuestro schema unificado."""
    fecha_raw = raw.get("publication_date", "")
    fecha_iso = fecha_raw.split("T")[0] if fecha_raw else ""

    return {
        "id":               f"remotive-{raw.get('id', '')}",
        "source":           "remotive",
        "empresa":          raw.get("company_name", "").strip(),
        "puesto":           raw.get("title", "").strip(),
        "descripcion":      limpiar_html(raw.get("description", ""), max_chars=1000),
        "tags":             [t.strip() for t in (raw.get("tags") or []) if t.strip()],
        "modalidad":        "Remoto",  # Remotive solo tiene ofertas remotas
        "ubicacion":        raw.get("candidate_required_location", "").strip(),
        "salario":          (raw.get("salary") or "").strip().replace("-", "").strip(),
        "tipo_contrato":    raw.get("job_type", ""),
        "link":             raw.get("url", ""),
        "fecha_publicacion": fecha_iso,
        "logo_empresa":     raw.get("company_logo", ""),
    }


# ══════════════════════════════════════════════
# REMOTIVE — fuente de ofertas reales
# ══════════════════════════════════════════════

def buscar_remotive(
    rol: str = "",
    categoria: str = "software-dev",
    max_results: int = 20,
) -> list:
    """
    Busca ofertas en Remotive y devuelve lista normalizada.

    Args:
        rol: término de búsqueda libre (ej. "frontend developer")
        categoria: filtro de categoría Remotive. Categorías válidas:
            software-dev, customer-support, design, marketing, sales,
            product, business, finance-legal, human-resources,
            qa, writing, data, devops-sysadmin, all-other-remote-jobs
        max_results: número máximo de ofertas a devolver

    Returns:
        Lista de ofertas normalizadas (dict con schema unificado).
        Lista vacía si la API falla.
    """
    params = {"category": categoria}
    if rol:
        params["search"] = rol

    try:
        resp = requests.get(REMOTIVE_API_URL, params=params, timeout=REMOTIVE_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Remotive API falló: %s", e)
        return []

    jobs_raw = data.get("jobs", []) or []
    logger.info("Remotive devolvió %d ofertas (rol='%s', categoria='%s')",
                len(jobs_raw), rol, categoria)

    ofertas = []
    for raw in jobs_raw[:max_results]:
        try:
            ofertas.append(normalizar_oferta_remotive(raw))
        except Exception as e:
            logger.warning("Error normalizando oferta Remotive: %s", e)
            continue

    return ofertas


# ══════════════════════════════════════════════
# FILTRADO LOCAL — preferencias del usuario
# ══════════════════════════════════════════════

def matchea_stack(oferta: dict, stack_usuario: list) -> int:
    """
    Cuenta cuántas tecnologías del stack del usuario aparecen en la oferta.
    Busca en tags, título y descripción (case-insensitive).
    """
    if not stack_usuario:
        return 0

    texto = " ".join([
        oferta.get("puesto", ""),
        " ".join(oferta.get("tags", [])),
        oferta.get("descripcion", ""),
    ]).lower()

    coincidencias = 0
    for tech in stack_usuario:
        if not tech:
            continue
        # Match exacto de palabra (no substring), case-insensitive
        patron = r"\b" + re.escape(tech.lower()) + r"\b"
        if re.search(patron, texto):
            coincidencias += 1

    return coincidencias


def filtrar_por_perfil(
    ofertas: list,
    stack_usuario: list = None,
    min_matches_stack: int = 1,
) -> list:
    """
    Filtra ofertas que tengan al menos `min_matches_stack` tecnologías
    del stack del usuario. Si stack_usuario está vacío, no filtra.
    """
    if not stack_usuario:
        return ofertas

    filtradas = []
    for oferta in ofertas:
        matches = matchea_stack(oferta, stack_usuario)
        if matches >= min_matches_stack:
            oferta["_stack_matches"] = matches  # para usar después en orden
            filtradas.append(oferta)

    logger.info("Filtrado por stack: %d ofertas con ≥%d coincidencias (de %d totales)",
                len(filtradas), min_matches_stack, len(ofertas))
    return filtradas


def deduplicar(ofertas: list) -> list:
    """Elimina duplicados basándose en (empresa + puesto). Mantiene la primera."""
    vistos = set()
    unicas = []
    for o in ofertas:
        key = (o.get("empresa", "").lower().strip(),
               o.get("puesto", "").lower().strip())
        if key in vistos:
            continue
        vistos.add(key)
        unicas.append(o)
    return unicas


# ══════════════════════════════════════════════
# RANKING CON LLM (Groq)
# ══════════════════════════════════════════════

def rankear_con_groq(
    ofertas: list,
    perfil: str,
    rol: str,
    stack: list,
    salario_min: int = 0,
    top_n: int = 5,
    api_key: str = None,
    model: str = None,
) -> list:
    """
    Pide a Groq que rankee las ofertas según encaje con el perfil.
    Devuelve top_n ofertas con campos adicionales `score` y `motivo`.

    Si la llamada al LLM falla, devuelve las top_n ofertas ordenadas por
    `_stack_matches` (fallback heurístico).
    """
    if not ofertas:
        return []

    # Si solo hay top_n o menos, no merece la pena pedir ranking
    if len(ofertas) <= top_n:
        return [{**o, "score": 70, "motivo": "Encaje básico por filtro de stack"}
                for o in ofertas]

    api_key = api_key or os.getenv("GROQ_API_KEY", "")
    model = model or os.getenv("GROQ_MODEL", GROQ_MODEL_DEFAULT)

    if not api_key:
        logger.warning("No hay GROQ_API_KEY — usando fallback heurístico")
        return _ranking_fallback(ofertas, top_n)

    # Construir lista compacta para el prompt (sin descripción larga)
    ofertas_compactas = [
        {
            "id": i,
            "empresa":     o.get("empresa", ""),
            "puesto":      o.get("puesto", ""),
            "tags":        o.get("tags", [])[:8],
            "ubicacion":   o.get("ubicacion", ""),
            "salario":     o.get("salario", ""),
            "tipo":        o.get("tipo_contrato", ""),
            "resumen":     (o.get("descripcion", "") or "")[:300],
        }
        for i, o in enumerate(ofertas)
    ]

    prompt = f"""Eres un recruiter senior. Tienes este candidato:

PERFIL: {perfil}
ROL OBJETIVO: {rol}
STACK PRINCIPAL: {", ".join(stack) if stack else "(no especificado)"}
SALARIO MÍNIMO: {salario_min}€/año (0 = sin preferencia)

OFERTAS DISPONIBLES ({len(ofertas_compactas)} ofertas):
{json.dumps(ofertas_compactas, ensure_ascii=False, indent=2)}

TU TAREA:
Selecciona las {top_n} mejores ofertas para este candidato y dame un ranking.
Considera:
1. Encaje del stack tecnológico (lo más importante)
2. Match del rol/seniority
3. Ubicación compatible (España, Europa, Worldwide remote)
4. Tipo de contrato razonable

Devuelve SOLAMENTE un JSON array (sin explicaciones, sin markdown), formato:
[
  {{"id": 3, "score": 92, "motivo": "Frase corta: por qué encaja"}},
  {{"id": 7, "score": 88, "motivo": "..."}},
  ...
]

Score: 0-100. Motivo: máximo 15 palabras en español.
"""

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model":      model,
                "messages":   [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
                "temperature": 0.3,
            },
            timeout=GROQ_TIMEOUT,
        )
        resp.raise_for_status()
        raw_content = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("Groq ranking falló: %s — usando fallback heurístico", e)
        return _ranking_fallback(ofertas, top_n)

    # Parsear el JSON que devuelve el LLM (puede venir con markdown wrapper)
    json_match = re.search(r"\[\s*\{.*?\}\s*\]", raw_content, re.DOTALL)
    if not json_match:
        logger.warning("Groq no devolvió JSON parseable: %s", raw_content[:200])
        return _ranking_fallback(ofertas, top_n)

    try:
        rankings = json.loads(json_match.group(0))
    except json.JSONDecodeError as e:
        logger.warning("JSON inválido del LLM: %s", e)
        return _ranking_fallback(ofertas, top_n)

    # Combinar rankings con ofertas originales
    resultado = []
    for r in rankings[:top_n]:
        idx = r.get("id", -1)
        if 0 <= idx < len(ofertas):
            oferta_completa = {
                **ofertas[idx],
                "score":  r.get("score", 50),
                "motivo": r.get("motivo", ""),
            }
            resultado.append(oferta_completa)

    logger.info("Ranking LLM OK: %d ofertas seleccionadas", len(resultado))
    return resultado


def _ranking_fallback(ofertas: list, top_n: int) -> list:
    """Ranking heurístico cuando el LLM no está disponible."""
    ordenadas = sorted(
        ofertas,
        key=lambda o: o.get("_stack_matches", 0),
        reverse=True,
    )
    return [
        {
            **o,
            "score":  60 + (o.get("_stack_matches", 0) * 5),
            "motivo": f"Encaja en {o.get('_stack_matches', 0)} tecnologías de tu stack",
        }
        for o in ordenadas[:top_n]
    ]


# ══════════════════════════════════════════════
# FUNCIÓN ORQUESTADORA
# ══════════════════════════════════════════════

def buscar_ofertas_reales(
    perfil: str,
    rol: str,
    stack: list,
    salario_min: int = 0,
    modalidad: list = None,
    ciudad: str = "",
    top_n: int = 5,
) -> dict:
    """
    Pipeline completo: buscar → filtrar → rankear → devolver.

    Returns:
        {
            "ok": True,
            "ofertas": [...],          # top_n ofertas con score y motivo
            "total_encontradas": 21,
            "total_filtradas": 8,
            "fuente": "remotive"
        }
    """
    rol_busqueda = rol or (stack[0] if stack else "")

    # 1. Buscar en Remotive
    ofertas_raw = buscar_remotive(rol=rol_busqueda, max_results=20)

    if not ofertas_raw:
        return {
            "ok":       False,
            "error":    "No se encontraron ofertas en Remotive",
            "ofertas":  [],
            "total_encontradas": 0,
        }

    # 2. Deduplicar
    unicas = deduplicar(ofertas_raw)

    # 3. Filtrar por stack (solo si stack tiene contenido)
    filtradas = filtrar_por_perfil(unicas, stack_usuario=stack, min_matches_stack=1)

    # Si no quedan tras filtrar, usar las originales (fallback)
    if not filtradas:
        logger.info("Sin matches de stack — usando ofertas sin filtrar")
        filtradas = unicas

    # 4. Rankear con LLM
    top = rankear_con_groq(
        filtradas,
        perfil=perfil,
        rol=rol,
        stack=stack,
        salario_min=salario_min,
        top_n=top_n,
    )

    return {
        "ok":                True,
        "ofertas":           top,
        "total_encontradas": len(ofertas_raw),
        "total_filtradas":   len(filtradas),
        "fuente":            "remotive",
    }


# ══════════════════════════════════════════════
# MAIN — test manual standalone
# ══════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("\n🔍 TEST 1 — Buscar 'frontend' en Remotive (raw)\n")
    ofertas = buscar_remotive(rol="frontend", max_results=5)
    print(f"   → {len(ofertas)} ofertas encontradas")
    for i, o in enumerate(ofertas[:3], 1):
        print(f"   {i}. {o['empresa']} · {o['puesto']}")
        print(f"      tags: {', '.join(o['tags'][:5])}")
        print(f"      ubicación: {o['ubicacion']}")

    print("\n🎯 TEST 2 — Pipeline completo (perfil de Verónica)\n")
    resultado = buscar_ofertas_reales(
        perfil="Senior Frontend Developer con experiencia en React, TypeScript y arquitectura UX",
        rol="frontend",
        stack=["React", "TypeScript", "JavaScript", "Vue"],
        salario_min=50000,
        modalidad=["Remoto"],
        ciudad="Madrid",
        top_n=3,
    )

    print(f"\n   Total encontradas: {resultado.get('total_encontradas')}")
    print(f"   Total tras filtro: {resultado.get('total_filtradas')}")
    print(f"   Top devuelto:      {len(resultado.get('ofertas', []))}\n")

    for i, o in enumerate(resultado.get("ofertas", []), 1):
        print(f"   {i}. [{o.get('score', '?')}/100] {o['empresa']} · {o['puesto']}")
        print(f"      → {o.get('motivo', '')}")
        print(f"      → {o['link']}")
        print()
