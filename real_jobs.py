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
import xml.etree.ElementTree as ET

import match

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
REMOTIVE_TIMEOUT = 15  # segundos

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_DEFAULT = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile lo retiro Groq el 16-ago-2026
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

    # Normalizar: aceptar strings con espacios/comas y minúsculas.
    stack_norm = []
    for tech in stack_usuario:
        if isinstance(tech, str):
            stack_norm.extend([t.strip().lower() for t in re.split(r"[,\s]+", tech) if t.strip()])
        elif tech:
            stack_norm.append(str(tech).strip().lower())

    if not stack_norm:
        return 0

    texto = " ".join([
        oferta.get("puesto", ""),
        " ".join(oferta.get("tags", [])),
        oferta.get("descripcion", ""),
    ]).lower()

    coincidencias = 0
    for tech in stack_norm:
        # Match exacto de palabra (no substring), case-insensitive
        patron = r"\b" + re.escape(tech) + r"\b"
        if re.search(patron, texto):
            coincidencias += 1

    return coincidencias


KEYWORDS_IA = ("ai", "ml", "llm", "generative", "machine learning", "deep learning",
               "nlp", "computer vision", "data science", "artificial intelligence")


# Términos que suelen indicar spam / ofertas no reales (cursos, bootcamps, etc.).
TAGS_SPAM = ("bootcamp", "curso", "course", "masterclass", "webinar", "tutorial",
             "prácticas no remuneradas", "sin remunerar", "unpaid internship")


def filtrar_spam(ofertas: list, tags_spam=None) -> list:
    """Descarta ofertas cuyo texto contenga términos de spam (case-insensitive)."""
    if tags_spam is None:
        tags_spam = TAGS_SPAM
    terminos = [t.strip().lower() for t in tags_spam if t and str(t).strip()]
    if not terminos:
        return list(ofertas)
    salida = []
    for oferta in ofertas:
        texto = " ".join([
            oferta.get("puesto", "") or "",
            " ".join(oferta.get("tags", []) or []),
            oferta.get("descripcion", "") or "",
            oferta.get("empresa", "") or "",
        ]).lower()
        if any(t in texto for t in terminos):
            continue
        salida.append(oferta)
    logger.info("Filtro spam: %d ofertas (de %d)", len(salida), len(ofertas))
    return salida


import re as _re


def _salario_anual(salario: str) -> int | None:
    """Extrae un salario anual aproximado de un texto libre. None si no es parseable."""
    if not salario:
        return None
    texto = str(salario).lower().replace(" ", "")
    # Detectar periodicidad mensual.
    mensual = "mes" in texto or "month" in texto
    # Buscar el primer número (con opcional 'k').
    m = _re.search(r"(\d+(?:[.,]\d+)?)\s*k", texto)
    if m:
        valor = float(m.group(1).replace(",", "."))
        anual = int(valor * 1000)
        return anual * 12 if mensual else anual
    m = _re.search(r"(\d{3,})", texto)
    if m:
        valor = float(m.group(1))
        anual = int(valor)
        return anual * 12 if mensual else anual
    return None


def filtrar_por_salario(ofertas: list, salario_min: int = 0) -> list:
    """Descarta ofertas con salario parseable inferior a salario_min.

    Las ofertas sin salario parseable se conservan (no se asume que no cumplen).
    """
    if not salario_min:
        return list(ofertas)
    salida = []
    for oferta in ofertas:
        anual = _salario_anual(oferta.get("salario", "") or "")
        if anual is not None and anual < salario_min:
            continue
        salida.append(oferta)
    logger.info("Filtro salario (min %s): %d ofertas (de %d)", salario_min, len(salida), len(ofertas))
    return salida


def tiene_keyword_ia(oferta: dict, keywords=None) -> bool:
    """True si la oferta menciona alguna keyword de IA en puesto/tags/descripcion."""
    if keywords is None:
        keywords = KEYWORDS_IA
    texto = " ".join([
        oferta.get("puesto", ""),
        " ".join(oferta.get("tags", []) or []),
        oferta.get("descripcion", ""),
    ]).lower()
    return any(k in texto for k in (k.lower() for k in keywords))


def region_remota_compatible(ubicacion_oferta: str, regiones_usuario=None, ciudad_usuario: str = "") -> bool:
    """True si una oferta remota acepta la region/pais del usuario."""
    ubi = (ubicacion_oferta or "").strip().lower()
    if not ubi:
        return True
    universales = ("worldwide", "anywhere", "global", "remote", "eu", "europe", "spain", "españa", "emea")
    if any(u in ubi for u in universales):
        return True
    regiones = [r.lower() for r in (regiones_usuario or [])]
    if regiones and any(r in ubi for r in regiones):
        return True
    if ciudad_usuario and ciudad_usuario.lower() in ubi:
        return True
    regiones_conocidas = ("usa", "united states", "uk", "united kingdom", "canada", "latam",
                          "apac", "asia", "africa", "india", "australia")
    if any(r in ubi for r in regiones_conocidas):
        return False
    return True


def filtrar_por_perfil(
    ofertas: list,
    stack_usuario: list = None,
    min_matches_stack: int = 1,
    keywords_ia=None,
) -> list:
    """Prefiltro de stack: descarta solo ofertas con 0 coincidencias de stack Y sin
    keyword de IA. Las demas pasan (y se anota `_stack_matches`)."""
    if keywords_ia is None:
        keywords_ia = KEYWORDS_IA
    if not stack_usuario:
        stack_usuario = []

    filtradas = []
    for oferta in ofertas:
        matches = matchea_stack(oferta, stack_usuario) if stack_usuario else 0
        if stack_usuario and matches < min_matches_stack and not tiene_keyword_ia(oferta, keywords_ia):
            continue
        oferta["_stack_matches"] = matches
        filtradas.append(oferta)

    logger.info("Filtrado por stack: %d ofertas (de %d totales)", len(filtradas), len(ofertas))
    return filtradas


def aplicar_evitar(ofertas: list, evitar=None) -> list:
    """Descarta ofertas que matcheen `evitar` (substring case-insensitive)."""
    if not evitar:
        return ofertas
    terminos = [t.strip().lower() for t in str(evitar).split(",") if t.strip()]
    if not terminos:
        return ofertas
    salida = []
    for oferta in ofertas:
        texto = " ".join([
            oferta.get("puesto", ""),
            " ".join(oferta.get("tags", []) or []),
            oferta.get("descripcion", ""),
        ]).lower()
        if any(t in texto for t in terminos):
            continue
        salida.append(oferta)
    return salida


def filtrar_por_modalidad(
    ofertas: list,
    modalidad_usuario=None,
    ciudad_usuario: str = "",
    ciudades_hibrido=None,
    regiones_remoto=None,
    evitar=None,
) -> list:
    """Porta 'Code - Normalizar Modalidad' per usuaria."""
    if modalidad_usuario is None:
        modalidad_usuario = []
    mod = [str(m).lower() for m in (modalidad_usuario or [])]
    acepta_remoto = any(m in ("remoto", "remote") for m in mod)
    acepta_hibrido = any(m in ("hibrido", "hybrid", "híbrido") for m in mod)
    acepta_presencial = any(m in ("presencial", "on-site", "onsite") for m in mod)

    ciudades_hib = [c.strip() for c in (ciudades_hibrido or []) if c and str(c).strip()]
    ciudades_hib_low = {c.lower(): c for c in ciudades_hib}

    salida = []
    for oferta in ofertas:
        modalidad_oferta = (oferta.get("modalidad") or "").lower()
        ubicacion = oferta.get("ubicacion") or ""
        ciudad_oferta = ubicacion.split(",")[0].strip() if ubicacion else ""

        if "remoto" in modalidad_oferta or modalidad_oferta == "remote":
            if acepta_remoto and region_remota_compatible(ubicacion, regiones_remoto, ciudad_usuario):
                salida.append(oferta)
            continue

        if "hibrid" in modalidad_oferta or "híbrid" in modalidad_oferta or "hybrid" in modalidad_oferta:
            if not acepta_hibrido:
                continue
            ciudad_low = ciudad_oferta.lower()
            if ciudad_usuario and ciudad_low == ciudad_usuario.lower():
                salida.append(oferta)
                continue
            if ciudad_low in ciudades_hib_low:
                copia = dict(oferta)
                copia["notas"] = f"HIBRIDO {ciudades_hib_low[ciudad_low].upper()}: confirmar días de oficina"
                salida.append(copia)
                continue
            continue

        if "presencial" in modalidad_oferta or "on-site" in modalidad_oferta or "onsite" in modalidad_oferta:
            if acepta_presencial and ciudad_usuario and ciudad_oferta.lower() == ciudad_usuario.lower():
                salida.append(oferta)
            continue

        salida.append(oferta)

    salida = aplicar_evitar(salida, evitar)
    logger.info("Filtrado por modalidad: %d ofertas (de %d)", len(salida), len(ofertas))
    return salida


def buscar_tecnoempleo(rol: str = "", max_results: int = 20) -> list:
    """Busca ofertas en Tecnoempleo RSS. Devuelve lista normalizada (puede estar vacía)."""
    url = "https://www.tecnoempleo.com/rss/ofertas-empleo.xml"
    if rol:
        url = f"https://www.tecnoempleo.com/rss/ofertas-empleo.xml?k={rol}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Tecnoempleo RSS falló: %s", e)
        return []
    try:
        root = ET.fromstring(resp.content)
    except Exception as e:
        logger.error("Tecnoempleo XML inválido: %s", e)
        return []
    ofertas = []
    for item in root.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        fecha = (item.findtext("pubDate") or "").strip()
        if not titulo:
            continue
        ofertas.append({
            "id": f"tecnoempleo-{hash(titulo + link)}",
            "source": "tecnoempleo",
            "empresa": "",
            "puesto": titulo,
            "descripcion": limpiar_html(desc, max_chars=1000),
            "tags": [],
            "modalidad": "Remoto",
            "ubicacion": "",
            "salario": "",
            "tipo_contrato": "",
            "link": link,
            "fecha_publicacion": fecha,
            "logo_empresa": "",
        })
        if len(ofertas) >= max_results:
            break
    logger.info("Tecnoempleo: %d ofertas (rol='%s')", len(ofertas), rol)
    return ofertas


def buscar_google_jobs(rol: str = "", api_key: str = None, max_results: int = 20) -> list:
    """Busca ofertas en Google Jobs via SerpApi. Devuelve lista normalizada (puede estar vacía)."""
    api_key = api_key or os.getenv("SERPAPI_KEY", "")
    if not api_key:
        logger.warning("No SERPAPI_KEY — saltando Google Jobs")
        return []
    params = {
        "engine": "google_jobs",
        "q": rol or "software developer",
        "api_key": api_key,
        "num": max_results,
    }
    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Google Jobs (SerpApi) falló: %s", e)
        return []
    jobs = data.get("jobs_results", []) or []
    ofertas = []
    for raw in jobs[:max_results]:
        titulo = raw.get("title", "").strip()
        empresa = raw.get("company_name", "").strip()
        if not titulo:
            continue
        ofertas.append({
            "id": f"googlejobs-{raw.get('job_id', hash(titulo + empresa))}",
            "source": "google_jobs",
            "empresa": empresa,
            "puesto": titulo,
            "descripcion": limpiar_html(raw.get("description", ""), max_chars=1000),
            "tags": raw.get("detected_extensions", {}).get("qualifications", []) or [],
            "modalidad": raw.get("detected_extensions", {}).get("work_from_home", "Remoto") or "Remoto",
            "ubicacion": raw.get("location", "").strip(),
            "salario": raw.get("detected_extensions", {}).get("salary", "") or "",
            "tipo_contrato": raw.get("detected_extensions", {}).get("schedule_type", "") or "",
            "link": raw.get("related_links", [{}])[0].get("link", "") if raw.get("related_links") else "",
            "fecha_publicacion": raw.get("detected_extensions", {}).get("posted_at", "") or "",
            "logo_empresa": raw.get("thumbnail", "") or "",
        })
    logger.info("Google Jobs: %d ofertas (rol='%s')", len(ofertas), rol)
    return ofertas


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
    perfil_usuario=None,
    perfil: str = "",
    rol: str = "",
    stack: list = None,
    salario_min: int = 0,
    modalidad: list = None,
    ciudad: str = "",
    regiones_remoto=None,
    ciudades_hibrido=None,
    evitar=None,
    tarifa_dia_min=None,
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
    if stack is None:
        stack = []
    if modalidad is None:
        modalidad = []

    # Desempaquetar perfil completo si se pasa como dict.
    if isinstance(perfil_usuario, dict):
        perfil = perfil_usuario.get("perfil") or perfil_usuario.get("perfil_texto") or perfil or ""
        rol = perfil_usuario.get("rol") or perfil_usuario.get("rol_objetivo") or rol
        stack = perfil_usuario.get("stack") or stack
        salario_min = perfil_usuario.get("salario_min") or perfil_usuario.get("salario") or salario_min
        modalidad = perfil_usuario.get("modalidad") or modalidad
        ciudad = perfil_usuario.get("ubicacion") or perfil_usuario.get("ciudad") or ciudad
        regiones_remoto = perfil_usuario.get("regiones_remoto") or regiones_remoto
        ciudades_hibrido = perfil_usuario.get("ciudades_hibrido") or ciudades_hibrido
        evitar = perfil_usuario.get("evitar") or evitar
        tarifa_dia_min = perfil_usuario.get("tarifa_dia_min") or tarifa_dia_min
    if not perfil and perfil_usuario and not isinstance(perfil_usuario, dict):
        perfil = str(perfil_usuario)

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

    tarifa_dia = tarifa_dia_min or (int(salario_min / 150) if salario_min else 0)
    tarifa_hora = int(salario_min / 1200) if salario_min else 0

    prompt = f"""Eres un recruiter senior. Tienes este candidato:

PERFIL: {perfil}
ROL OBJETIVO: {rol}
STACK PRINCIPAL: {", ".join(stack) if stack else "(no especificado)"}
AÑOS EXPERIENCIA: {perfil_usuario.get("anios_experiencia") if isinstance(perfil_usuario, dict) else ""}
CIUDAD: {ciudad or "(no especificada)"}
MODALIDAD ACEPTADA: {", ".join(modalidad) if modalidad else "(no especificada)"}
REGIONES REMOTO: {", ".join(regiones_remoto or []) or "(sin restriccion)"}
CIUDADES HIBRIDO OCASIONAL: {", ".join(ciudades_hibrido or []) or "(ninguna)"}
SALARIO MÍNIMO: {salario_min}€/año (0 = sin preferencia)
TARIFA FREELANCE: {tarifa_dia}€/dia, {tarifa_hora}€/hora (derivadas)
EVITAR: {evitar or "(nada)"}

OFERTAS DISPONIBLES ({len(ofertas_compactas)} ofertas):
{json.dumps(ofertas_compactas, ensure_ascii=False, indent=2)}

TU TAREA:
Selecciona las {top_n} mejores ofertas para este candidato y dame un ranking.
Considera:
1. Encaje del stack tecnológico (lo más importante)
2. Match del rol/seniority
3. Ubicación compatible: remoto solo si la región acepta al usuario; híbrido en ciudad propia u ocasional (marcar HIBRIDO <CIUDAD> en motivo); presencial solo en su ciudad.
4. Descarta cualquier oferta que encaje en EVITAR.
5. Un rol frontend puro es tan válido como AI/full-stack.
6. Tipo de contrato razonable (freelance: aplicar tarifa mínima).

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


def _ranking_fallback(ofertas: list, top_n: int, master_texto: str = None) -> list:
    """Ranking heurístico cuando el LLM no está disponible.

    Sin `master_texto` conserva el orden de siempre (por `_stack_matches`).
    Con él, usa el encaje honesto de `match.py`: alcanzable primero, luego
    cobertura, y a igualdad remoto, con sueldo declarado y `_stack_matches`.
    """
    if not master_texto:
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

    evaluadas = []
    for o in ofertas:
        texto = " ".join([o.get("puesto", ""), " ".join(o.get("tags", [])),
                          o.get("descripcion", "")])
        evaluadas.append((o, match.evaluar(texto, {}, master_texto)))
    evaluadas.sort(
        key=lambda par: (
            par[1].alcanzable,
            par[1].cobertura,
            (par[0].get("modalidad") or "").lower() == "remoto",
            bool(par[0].get("salario")),
            par[0].get("_stack_matches", 0),
        ),
        reverse=True,
    )
    resultado = []
    for o, e in evaluadas[:top_n]:
        if e.tecnologias_pedidas:
            motivo = f"Cubres {e.tecnologias_cubiertas} de {e.tecnologias_pedidas}"
            if e.tecnologias_hueco:
                motivo += "; te falta: " + ", ".join(e.tecnologias_hueco)
        else:
            motivo = "No se pueden evaluar requisitos concretos de esta oferta"
        resultado.append({**o, "score": 50 + round(e.cobertura * 45), "motivo": motivo})
    return resultado


# ══════════════════════════════════════════════
# FUNCIÓN ORQUESTADORA
# ══════════════════════════════════════════════

def buscar_ofertas_reales(
    perfil=None,
    perfil_usuario=None,
    *,
    rol: str = "",
    stack: list = None,
    salario_min: int = 0,
    modalidad: list = None,
    ciudad: str = "",
    regiones_remoto=None,
    ciudades_hibrido=None,
    evitar=None,
    tarifa_dia_min=None,
    anios_experiencia=None,
    idiomas=None,
    perfil_texto: str = "",
    top_n: int = 5,
    api_key: str = None,
    model: str = None,
    progress_cb=None,
) -> dict:
    """
    Pipeline completo: buscar → dedup → filtrar stack → filtrar modalidad → rankear.

    Acepta `perfil`/`perfil_usuario` como dict completo (Postgres) o str legacy.
    Los kwargs explícitos sobrescriben los valores del dict.
    """
    if stack is None:
        stack = []
    if modalidad is None:
        modalidad = []

    pu = perfil_usuario if perfil_usuario is not None else perfil
    perfil_dict = pu if isinstance(pu, dict) else None

    if perfil_dict:
        rol = rol or perfil_dict.get("rol") or perfil_dict.get("rol_objetivo") or ""
        stack = stack or (perfil_dict.get("stack") or [])
        salario_min = salario_min or perfil_dict.get("salario_min") or perfil_dict.get("salario") or 0
        modalidad = modalidad or (perfil_dict.get("modalidad") or [])
        ciudad = ciudad or perfil_dict.get("ubicacion") or perfil_dict.get("ciudad") or ""
        regiones_remoto = regiones_remoto if regiones_remoto is not None else perfil_dict.get("regiones_remoto")
        ciudades_hibrido = ciudades_hibrido if ciudades_hibrido is not None else perfil_dict.get("ciudades_hibrido")
        evitar = evitar if evitar is not None else perfil_dict.get("evitar")
        tarifa_dia_min = tarifa_dia_min if tarifa_dia_min is not None else perfil_dict.get("tarifa_dia_min")
        anios_experiencia = anios_experiencia if anios_experiencia is not None else perfil_dict.get("anios_experiencia")
        idiomas = idiomas if idiomas is not None else perfil_dict.get("idiomas")
        perfil_texto = perfil_texto or perfil_dict.get("perfil") or perfil_dict.get("perfil_texto") or ""
    else:
        if isinstance(pu, str):
            perfil_texto = perfil_texto or pu

    rol_busqueda = rol or (stack[0] if stack else "")

    # 1. Buscar en todas las fuentes disponibles
    ofertas_raw = []
    ofertas_raw.extend(buscar_remotive(rol=rol_busqueda, max_results=20))
    if progress_cb: progress_cb({"stage": "searching", "source": "remotive", "count": len(ofertas_raw)})
    ofertas_raw.extend(buscar_tecnoempleo(rol=rol_busqueda, max_results=20))
    if progress_cb: progress_cb({"stage": "searching", "source": "tecnoempleo", "count": len(ofertas_raw)})
    ofertas_raw.extend(buscar_google_jobs(rol=rol_busqueda, max_results=20))
    if progress_cb: progress_cb({"stage": "searching", "source": "google_jobs", "count": len(ofertas_raw)})

    if not ofertas_raw:
        return {
            "ok":       False,
            "error":    "No se encontraron ofertas en ninguna fuente",
            "ofertas":  [],
            "total_encontradas": 0,
            "total_filtradas": 0,
        }

    # 2. Deduplicar
    unicas = deduplicar(ofertas_raw)
    total_encontradas = len(ofertas_raw)
    if progress_cb: progress_cb({"stage": "dedup", "count": len(unicas)})

    # 2b. Filtro de spam (cursos, bootcamps, etc.)
    unicas = filtrar_spam(unicas)
    if progress_cb: progress_cb({"stage": "spam", "count": len(unicas)})

    # 3. Prefiltro de stack (+ keyword IA)
    filtradas = filtrar_por_perfil(unicas, stack_usuario=stack, min_matches_stack=1)
    if progress_cb: progress_cb({"stage": "filtering", "count": len(filtradas)})

    if not filtradas:
        logger.info("Sin matches de stack — usando ofertas sin filtrar")
        filtradas = unicas

    # 4. Filtro por modalidad / region / evitar
    if progress_cb: progress_cb({"stage": "modalidad", "count": len(filtradas)})
    filtradas = filtrar_por_modalidad(
        filtradas,
        modalidad_usuario=modalidad,
        ciudad_usuario=ciudad,
        ciudades_hibrido=ciudades_hibrido,
        regiones_remoto=regiones_remoto,
        evitar=evitar,
    )

    if not filtradas:
        logger.info("Sin ofertas tras filtro de modalidad — usando deduplicadas")
        filtradas = unicas

    # 4b. Filtro de salario mínimo (hard filter cuando el salario es parseable)
    if salario_min:
        filtradas = filtrar_por_salario(filtradas, salario_min=salario_min)
        if progress_cb: progress_cb({"stage": "salario", "count": len(filtradas)})
        if not filtradas:
            logger.info("Sin ofertas tras filtro de salario — usando anteriores")
            filtradas = unicas

    # 5. Rankear con LLM
    if progress_cb: progress_cb({"stage": "ranking"})
    top = rankear_con_groq(
        filtradas,
        perfil_usuario=perfil_dict if perfil_dict else None,
        perfil=perfil_texto,
        rol=rol,
        stack=stack,
        salario_min=salario_min,
        modalidad=modalidad,
        ciudad=ciudad,
        regiones_remoto=regiones_remoto,
        ciudades_hibrido=ciudades_hibrido,
        evitar=evitar,
        tarifa_dia_min=tarifa_dia_min,
        top_n=top_n,
        api_key=api_key,
        model=model,
    )

    return {
        "ok":                True,
        "ofertas":           top,
        "total_encontradas": total_encontradas,
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
