#!/usr/bin/env python3
"""
cv_server_railway.py  —  v2.3-groq
LLM: Groq (primario) → Gemini (fallback) → Claude (fallback)

Formulario multi-pantalla:
  1a. Email only → detecta si existe
  2a. Si existe → "¡Hola de nuevo!" + botones Buscar ahora / Mañana 9am
  1.  Si nuevo → formulario completo + botón Buscar ahora
"""

import os
import io
import logging
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template_string

# Google Drive / OAuth
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Claude (calidad — CV y textos que van a empresas)
import anthropic

# DOCX
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Búsqueda de ofertas reales (Fase 3.0)
from real_jobs import buscar_ofertas_reales

# ─────────────────────────────────────────────
# CONFIGURACIÓN — solo variables de entorno
# ─────────────────────────────────────────────

# ── LLM: Groq (primario) ──────────────────────
GROQ_API_KEY = os.environ["GROQ_API_KEY"]                          # requerido
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # default razonable

# ── LLM: Gemini (fallback opcional) ──────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# ── LLM: Claude (fallback opcional) ──────────
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")

# ── Claude para el CV (calidad — va a empresas; Groq queda de fallback) ──
# Haiku 4.5: barato (~$0,02/CV) y sigue bien el prompt de adaptación.
CV_MODEL = os.getenv("CV_MODEL", "claude-haiku-4-5")
# Carta de presentación: Sonnet 4.6 (mejor prosa, ~$0,04/carta). Va a empresas.
CARTA_MODEL = os.getenv("CARTA_MODEL", "claude-sonnet-4-6")

# ── Google Drive ──────────────────────────────
GOOGLE_CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
FOLDER_CV_MASTERS    = os.getenv("FOLDER_CV_MASTERS", "1duJA_G3lLbOqiUYoSJcsXAvbtJUdcmzR")

# ── Notion ────────────────────────────────────
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_USUARIOS = os.getenv("NOTION_DB_USUARIOS", "")

# ── Webhooks n8n ──────────────────────────────
WEBHOOK_NUEVO_USUARIO = os.getenv("WEBHOOK_NUEVO_USUARIO", "")
WEBHOOK_BUSCAR_AHORA  = os.getenv("WEBHOOK_BUSCAR_AHORA", "")

# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ══════════════════════════════════════════════
# CAPA LLM — Groq primario, Gemini/Claude fallback
# ══════════════════════════════════════════════

def call_llm(prompt: str) -> str:
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
        return content
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
            return content
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
            return content
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


def call_llm_calidad(prompt: str, model: str = CV_MODEL, max_tokens: int = 4096) -> str:
    """Claude primario; si falla (rate limit, red o sin key) cae a Groq.
    Para el CV y textos que van a una empresa — mejor que Groq, ~$0,02/CV."""
    try:
        contenido = call_claude(prompt, model=model, max_tokens=max_tokens)
        logger.info("LLM calidad: Claude OK (%s)", model)
        return contenido
    except Exception as e:
        logger.warning("Claude falló (%s) — cayendo a Groq", e)
        return call_llm(prompt)


# ══════════════════════════════════════════════
# GOOGLE DRIVE
# ══════════════════════════════════════════════

def get_drive_service():
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds)


def subir_cv_a_drive(docx_bytes: bytes, nombre_archivo: str) -> str:
    service = get_drive_service()
    file_metadata = {
        "name":    nombre_archivo,
        "parents": [FOLDER_CV_MASTERS],
    }
    media = MediaIoBaseUpload(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    file = service.files().create(
        body=file_metadata, media_body=media, fields="id, webViewLink"
    ).execute()

    # Hacer público (solo lectura)
    service.permissions().create(
        fileId=file["id"],
        body={"role": "reader", "type": "anyone"},
    ).execute()

    return file.get("webViewLink", "")


# MimeTypes de Google Docs que necesitan export en vez de get_media
_GDOC_EXPORT = {
    "application/vnd.google-apps.document":       "text/plain",
    "application/vnd.google-apps.presentation":   "text/plain",
    "application/vnd.google-apps.spreadsheet":    "text/csv",
}


def leer_cv_master_desde_drive(usuario: dict, idioma: str = "es") -> str:
    """Descarga el CV master en texto plano desde Drive, eligiendo la fuente segun idioma.
    idioma='en' -> 'CV Master URL' (ingles); idioma='es' -> 'CV Master URL ES'
    (con fallback al master ingles si no hay version española configurada)."""
    service = get_drive_service()

    # Elegir la fuente del master segun el idioma detectado de la oferta
    if idioma == "en":
        file_id = (usuario.get("cv_master_file_id") or "").strip()
        url = usuario.get("cv_master_url", "") or ""
    else:  # 'es' (o cualquier otro) -> master español, con fallback al ingles
        file_id = ""
        url = usuario.get("cv_master_url_es", "") or ""
        if not url:
            file_id = (usuario.get("cv_master_file_id") or "").strip()
            url = usuario.get("cv_master_url", "") or ""

    # Si no hay file_id directo, extraerlo de la URL (link de Drive/Docs)
    if not file_id and url:
        import re
        m = re.search(r'/d/([a-zA-Z0-9_-]+)', url) or re.search(r'id=([a-zA-Z0-9_-]+)', url)
        if m:
            file_id = m.group(1)

    if not file_id:
        return ""

    try:
        # Detectar mimeType para saber cómo extraer el texto
        file_meta = service.files().get(fileId=file_id, fields="mimeType, name", supportsAllDrives=True).execute()
        mime = file_meta.get("mimeType", "")
        name = file_meta.get("name", "")

        if mime in _GDOC_EXPORT:
            # Google Docs nativos → exportar a texto
            export_mime = _GDOC_EXPORT[mime]
            req = service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            # Archivos binarios (DOCX, PDF, etc.) → get_media
            req = service.files().get_media(fileId=file_id)

        buf = io.BytesIO()
        from googleapiclient.http import MediaIoBaseDownload
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        buf.seek(0)

        # DOCX es un ZIP, NO texto plano: hay que parsearlo con python-docx.
        # Decodificar sus bytes como utf-8 devuelve basura ("PK...word/document.xml")
        # y el LLM nunca ve la experiencia real → CV genérico.
        DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if mime == DOCX_MIME or name.lower().endswith(".docx"):
            doc = Document(buf)
            partes = [p.text for p in doc.paragraphs if p.text.strip()]
            # Las skills suelen ir en tablas → también hay que extraerlas
            for tabla in doc.tables:
                for fila in tabla.rows:
                    for celda in fila.cells:
                        if celda.text.strip():
                            partes.append(celda.text)
            return "\n".join(partes)

        # Texto plano u otros formatos legibles
        return buf.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("No se pudo leer CV master (file_id=%s): %s", file_id, e)
        return ""


# ══════════════════════════════════════════════
# IDIOMA
# ══════════════════════════════════════════════

import re as _re_idioma

_ES_ACENTOS = _re_idioma.compile(r"[ñáéíóúü¿¡]", _re_idioma.IGNORECASE)
_ES_PALABRAS = {
    "experiencia", "equipo", "desarrollo", "empresa", "puesto", "requisitos",
    "conocimientos", "años", "trabajo", "ofrecemos", "buscamos", "gestión",
    "liderazgo", "desarrollador", "programador", "aplicaciones", "datos",
    "proyecto", "cliente", "habilidades", "capacidad", "valorable",
    "imprescindible", "nivel", "sector", "jornada", "remoto",
}
_EN_PALABRAS = {
    "experience", "team", "development", "company", "position", "requirements",
    "skills", "years", "work", "we", "you", "our", "developer", "engineer",
    "manage", "ability", "strong", "knowledge", "including", "required",
    "preferred", "remote", "build", "design", "role", "looking",
}


def detectar_idioma(*textos) -> str:
    """Heuristica simple: devuelve 'es' o 'en' segun señales del texto de la oferta.
    Acentos y signos ¿¡ pesan doble (señal fuerte de español). Empate -> 'es'
    (mercado principal de la usuaria)."""
    texto = " ".join(t for t in textos if t).lower()
    if not texto.strip():
        return "es"
    palabras = set(_re_idioma.findall(r"[a-záéíóúñü]+", texto))
    es = len(_ES_ACENTOS.findall(texto)) * 2
    es += sum(1 for w in _ES_PALABRAS if w in palabras)
    en = sum(1 for w in _EN_PALABRAS if w in palabras)
    return "en" if en > es else "es"


def _slug(texto: str) -> str:
    """Slug en minúsculas sin acentos para nombres de archivo."""
    s = (texto or "").lower().strip()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"),
                 ("ú", "u"), ("ñ", "n"), ("ü", "u")):
        s = s.replace(a, b)
    s = _re_idioma.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _nombre_archivo_cv(nombre: str, puesto: str) -> str:
    """Convención: cv-<nombre>-<puesto>-<año>.docx (ej: cv-veronica-serna-frontend-developer-2026.docx)."""
    partes = ["cv", _slug(nombre) or "candidato"]
    puesto_slug = _slug(puesto)
    if puesto_slug:
        partes.append(puesto_slug)
    partes.append(str(datetime.now(timezone.utc).year))
    return "-".join(partes) + ".docx"


def _tiene_algun_master(usuario: dict) -> bool:
    """True si el usuario tiene configurado un master en cualquier idioma."""
    return bool(
        (usuario.get("cv_master_file_id") or "").strip()
        or (usuario.get("cv_master_url") or "").strip()
        or (usuario.get("cv_master_url_es") or "").strip()
    )


# ══════════════════════════════════════════════
# NOTION
# ══════════════════════════════════════════════

def notion_headers():
    return {
        "Authorization":  f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json",
    }


def buscar_usuario_por_email(email: str) -> dict | None:
    """Consulta Notion por email. Devuelve perfil completo del usuario o None."""
    if not NOTION_DB_USUARIOS:
        return None
    resp = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}/query",
        headers=notion_headers(),
        json={"filter": {"property": "Email", "email": {"equals": email}}, "page_size": 1},
        timeout=15,
    )
    if resp.status_code != 200:
        logger.warning("Notion query error %s: %s", resp.status_code, resp.text[:200])
        return None
    results = resp.json().get("results", [])
    if not results:
        return None
    page = results[0]
    p = page.get("properties", {})
    return {
        "notion_id":          page.get("id", ""),
        "nombre":             (p.get("Name", {}).get("title") or [{}])[0].get("plain_text", ""),
        "email":              p.get("Email", {}).get("email", ""),
        "email_cv":           (p.get("Email CV", {}).get("email", "")
                               or (p.get("Email CV", {}).get("rich_text") or [{}])[0].get("plain_text", "")),
        "activo":             p.get("Activo", {}).get("checkbox", False),
        "perfil":             (p.get("Perfil", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "rol":                (p.get("Rol objetivo", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "stack":              [s["name"] for s in p.get("Stack", {}).get("multi_select", [])],
        "salario_min":        p.get("Salario min", {}).get("number", 0) or 0,
        "modalidad":          [m["name"] for m in p.get("Modalidad", {}).get("multi_select", [])],
        "ciudad":             (p.get("Ciudad", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "telefono":           (p.get("Teléfono", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "linkedin":           p.get("LinkedIn", {}).get("url", "") or "",
        "cv_master_url":      p.get("CV Master URL", {}).get("url", "") or "",
        "cv_master_url_es":   p.get("CV Master URL ES", {}).get("url", "") or "",
        "cv_master_file_id":  (p.get("cv_master_file_id", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
    }


def _extraer_drive_file_id(url: str) -> str:
    """Extrae el file ID de una URL de Google Drive."""
    import re
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url) or re.search(r'id=([a-zA-Z0-9_-]+)', url)
    return m.group(1) if m else ""


def crear_usuario_en_notion(datos: dict) -> dict:
    """Crea un usuario en la BD de Notion."""
    url = "https://api.notion.com/v1/pages"
    cv_master_url = datos.get("cv_master_url") or ""
    cv_master_file_id = _extraer_drive_file_id(cv_master_url) if cv_master_url else ""
    props = {
        "Name":           {"title":  [{"text": {"content": datos.get("nombre", "")}}]},
        "Email":          {"email":   datos.get("email", "")},
        "Perfil":         {"rich_text": [{"text": {"content": datos.get("perfil", "")}}]},
        "Rol objetivo":   {"rich_text": [{"text": {"content": datos.get("rol_objetivo", "") or datos.get("rol", "")}}]},
        "Stack":          {"multi_select": [{"name": s} for s in datos.get("stack", [])]},
        "Salario min":    {"number": datos.get("salario_min") or datos.get("salario") or 0},
        "Modalidad":      {"multi_select": [{"name": m} for m in datos.get("modalidad", [])]},
        "Ciudad":         {"rich_text": [{"text": {"content": datos.get("ciudad", "")}}]},
        "LinkedIn":       {"url": datos.get("linkedin") or None},
        "CV Master URL":  {"url": cv_master_url or None},
        "Activo":         {"checkbox": True},
    }
    if cv_master_file_id:
        props["cv_master_file_id"] = {"rich_text": [{"text": {"content": cv_master_file_id}}]}
    # Filtrar propiedades con valor None que Notion rechaza
    payload = {
        "parent": {"database_id": NOTION_DB_USUARIOS},
        "properties": {k: v for k, v in props.items() if v is not None and v != {"url": None}},
    }
    resp = requests.post(url, headers=notion_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ══════════════════════════════════════════════
# GENERACIÓN DOCX
# ══════════════════════════════════════════════

def generar_docx(contenido_cv: str, nombre_candidato: str) -> bytes:
    """Wrapper legacy — usar generar_docx_con_cabecera() para nuevos CVs."""
    return generar_docx_con_cabecera(contenido_cv, {"nombre": nombre_candidato})


def generar_docx_con_cabecera(contenido_cv: str, usuario: dict, titular: str = "") -> bytes:
    """Genera DOCX con cabecera profesional estructurada usando datos reales del usuario.
    `titular` (si viene) es el headline adaptado a la oferta por el LLM; tiene prioridad
    sobre el campo `rol` fijo del perfil."""
    from docx.shared import Cm
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    BLUE = RGBColor(0x1A, 0x56, 0xDB)
    DARK = RGBColor(0x1A, 0x1A, 0x1A)
    GREY = RGBColor(0x66, 0x66, 0x66)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    for section in doc.sections:
        section.top_margin    = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin   = Cm(2)
        section.right_margin  = Cm(2)

    # ── Cabecera ──────────────────────────────────────────────────
    nombre   = usuario.get("nombre", "Candidato")
    rol      = titular or usuario.get("rol", "")
    ciudad   = usuario.get("ciudad", "")
    telefono = usuario.get("telefono", "")
    # Email de cabecera (contacto) separado del email-clave de búsqueda en Notion
    email    = usuario.get("email_cv") or usuario.get("email", "")
    linkedin = (usuario.get("linkedin", "") or "").replace("https://", "").replace("http://", "")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(nombre.upper())
    r.bold = True; r.font.size = Pt(18); r.font.color.rgb = DARK

    if rol:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(rol)
        r.font.size = Pt(11); r.font.color.rgb = BLUE

    contacto = " · ".join(c for c in [ciudad, telefono, email, linkedin] if c)
    if contacto:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(contacto)
        r.font.size = Pt(8.5); r.font.color.rgb = GREY

    # Línea separadora
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single"); bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:space"), "2"); bottom.set(qn("w:color"), "1A56DB")
    pBdr.append(bottom); pPr.append(pBdr)

    # ── Cuerpo del CV ────────────────────────────────────────────
    SECCIONES = ["PERFIL PROFESIONAL", "EXPERIENCIA PROFESIONAL", "EXPERIENCIA",
                 "HABILIDADES TÉCNICAS", "HABILIDADES", "FORMACIÓN", "IDIOMAS",
                 "PROYECTOS", "CERTIFICACIONES", "COMPETENCIAS"]

    for linea in contenido_cv.strip().split("\n"):
        linea = linea.strip()
        if not linea:
            continue

        limpia = linea.upper().strip()

        # Sección
        if any(limpia.startswith(s) for s in SECCIONES) and len(linea) < 50:
            p = doc.add_paragraph()
            r = p.add_run(linea.upper())
            r.bold = True; r.font.size = Pt(10); r.font.color.rgb = BLUE
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after  = Pt(4)
            pPr = p._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single"); bottom.set(qn("w:sz"), "4")
            bottom.set(qn("w:space"), "2"); bottom.set(qn("w:color"), "1A56DB")
            pBdr.append(bottom); pPr.append(pBdr)
            continue

        # Bullet
        if linea.startswith(("- ", "• ", "* ")):
            p = doc.add_paragraph()
            r = p.add_run("• " + linea[2:].strip())
            r.font.size = Pt(9.5); r.font.color.rgb = DARK
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.space_after  = Pt(2)
            continue

        # Empresa / puesto (línea con — o –)
        if ("—" in linea or "–" in linea) and len(linea) < 100:
            p = doc.add_paragraph()
            r = p.add_run(linea)
            r.bold = True; r.font.size = Pt(10); r.font.color.rgb = DARK
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after  = Pt(1)
            continue

        # Fecha (línea corta con año)
        import re
        if re.search(r"(20\d{2}|19\d{2})", linea) and len(linea) < 60:
            p = doc.add_paragraph()
            r = p.add_run(linea)
            r.italic = True; r.font.size = Pt(9); r.font.color.rgb = GREY
            p.paragraph_format.space_after = Pt(2)
            continue

        # Texto normal
        p = doc.add_paragraph()
        r = p.add_run(linea)
        r.font.size = Pt(9.5); r.font.color.rgb = DARK
        p.paragraph_format.space_after = Pt(3)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ══════════════════════════════════════════════
# FORMULARIO HTML — 3 pantallas (email → existente | nuevo → completo)
# ══════════════════════════════════════════════

FORMULARIO_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>BuscarTrabajo — Registro</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #f0f4ff; display: flex;
           justify-content: center; align-items: flex-start; min-height: 100vh; padding: 2rem 1rem; }
    .card { background: #fff; border-radius: 16px; padding: 2rem; max-width: 520px;
            width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,.08); }
    h1 { font-size: 1.5rem; color: #1a56db; margin-bottom: .25rem; }
    .sub { color: #6b7280; font-size: .9rem; margin-bottom: 1.5rem; }
    label { display: block; font-size: .85rem; color: #374151; margin-bottom: .25rem; font-weight: 500; }
    input, textarea, select { width: 100%; padding: .6rem .8rem; border: 1px solid #d1d5db;
      border-radius: 8px; font-size: .95rem; margin-bottom: 1rem; }
    textarea { resize: vertical; min-height: 80px; }
    .screen { display: none; }
    .screen.active { display: block; }
    button { width: 100%; padding: .75rem; background: #1a56db; color: #fff;
             border: none; border-radius: 8px; font-size: 1rem; cursor: pointer; font-weight: 600; }
    button:hover { background: #1648c0; }
    button:disabled { background: #9ca3af; cursor: not-allowed; }
    button.secondary { background: #22c55e; }
    button.secondary:hover { background: #16a34a; }
    button.outline { background: #fff; color: #1a56db; border: 2px solid #1a56db; }
    button.outline:hover { background: #f0f7ff; }
    .button-row { display: flex; gap: .75rem; }
    .msg { margin-top: 1rem; padding: .75rem; border-radius: 8px; font-size: .9rem; }
    .ok  { background: #d1fae5; color: #065f46; }
    .err { background: #fee2e2; color: #991b1b; }
    .step { color: #9ca3af; font-size: .8rem; margin-bottom: 1rem; }
    .link-usuarios { text-align: center; margin-bottom: 1rem; }
    .link-usuarios a { color: #1a56db; font-size: .85rem; text-decoration: none; }
  </style>
</head>
<body>
<div class="card">
  <div class="link-usuarios">
    <a href="/usuarios" target="_blank">📋 Ver usuarios registrados</a>
  </div>

  <!-- PANTALLA 1a — Solo email (check si existe) -->
  <div id="sEmail" class="screen active">
    <h1>🚀 BuscarTrabajo.ai</h1>
    <p class="sub">Te buscamos trabajo mientras duermes.</p>
    <label>Email</label>
    <input id="emailInicial" type="email" placeholder="tu@email.com" />
    <button type="button" onclick="comprobarEmail()">Continuar →</button>
    <div id="msgEmail"></div>
  </div>

  <!-- PANTALLA 2a — Usuario existente -->
  <div id="sExistente" class="screen">
    <h1 id="saludoExistente">¡Hola de nuevo!</h1>
    <p class="sub">¿Cuándo quieres que busquemos ofertas?</p>
    <div class="button-row">
      <button class="secondary" onclick="accionExistente('ahora')">⚡ Buscar ahora</button>
      <button class="outline" onclick="accionExistente('manana')">🌅 Mañana a las 9</button>
    </div>
    <div id="msgExistente"></div>
  </div>

  <!-- PANTALLA 1 — Datos básicos (usuario nuevo) -->
  <div id="s1" class="screen">
    <h1>🎯 Cuéntanos qué buscas</h1>
    <p class="sub">Solo una vez — luego te buscamos ofertas cada día.</p>
    <p class="step">Paso 1 de 2</p>
    <label>Nombre completo</label>
    <input id="nombre" placeholder="Ana García López" />
    <label>Email</label>
    <input id="email" type="email" readonly style="background:#f0f0f0;color:#666;" />
    <label>Perfil profesional <span style="color:#9ca3af">(breve descripción)</span></label>
    <textarea id="perfil" placeholder="Desarrolladora frontend con 5 años de experiencia en React y Vue…"></textarea>
    <button type="button" onclick="irS2()">Continuar →</button>
  </div>

  <!-- PANTALLA 2 — Preferencias + Buscar ahora -->
  <div id="s2" class="screen">
    <p class="step">Paso 2 de 2</p>
    <label>Rol objetivo</label>
    <input id="rol" placeholder="Senior Frontend Developer" />
    <label>Stack principal <span style="color:#9ca3af">(separado por comas)</span></label>
    <input id="stack" placeholder="React, TypeScript, Node.js" />
    <label>Salario mínimo (€ bruto/año)</label>
    <input id="salario" type="number" placeholder="40000" />
    <label>Modalidad</label>
    <select id="modalidad">
      <option value="Remoto">Remoto</option>
      <option value="Híbrido">Híbrido</option>
      <option value="Presencial">Presencial</option>
    </select>
    <label>Ciudad (si aplica)</label>
    <input id="ciudad" placeholder="Madrid, Barcelona…" />
    <label>LinkedIn <span style="color:#9ca3af">(opcional)</span></label>
    <input id="linkedin" placeholder="https://linkedin.com/in/tu-perfil" />
    <label>CV Master (link Google Drive, opcional)</label>
    <input id="cv_master_url" placeholder="https://drive.google.com/file/d/..." />
    <button type="button" onclick="registrar()">🔍 Registrarme y buscar ahora</button>
    <div id="msg"></div>
  </div>

  <!-- PANTALLA 3 — Listo -->
  <div id="sListo" class="screen">
    <h1>✅ ¡Listo!</h1>
    <p class="sub" id="confirmacion">Todo en orden.</p>
  </div>
</div>

<script>
let currentEmail = '';
let currentNombre = '';

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

// PANTALLA 1a — comprobar email
async function comprobarEmail() {
  const email = document.getElementById('emailInicial').value.trim();
  const msg = document.getElementById('msgEmail');
  if (!email) {
    msg.innerHTML = '<div class="msg err">Introduce un email válido</div>';
    return;
  }
  currentEmail = email;
  const btn = document.querySelector('#sEmail button');
  btn.disabled = true;
  btn.textContent = 'Comprobando…';

  try {
    const resp = await fetch('/check-email', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ email })
    });
    const data = await resp.json();

    if (data.existe) {
      currentNombre = data.nombre || '';
      document.getElementById('saludoExistente').textContent = `¡Hola de nuevo, ${data.nombre || ''}!`;
      showScreen('sExistente');
    } else {
      document.getElementById('email').value = email;
      showScreen('s1');
    }
  } catch(e) {
    msg.innerHTML = '<div class="msg err">Error: ' + e.message + '</div>';
    btn.disabled = false;
    btn.textContent = 'Continuar →';
  }
}

// PANTALLA 2a — usuario existente
async function accionExistente(accion) {
  const msg = document.getElementById('msgExistente');
  try {
    const resp = await fetch('/accion-existente', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ email: currentEmail, nombre: currentNombre, accion })
    });
    await resp.json();
    if (accion === 'ahora') {
      document.getElementById('confirmacion').textContent =
        'Buscando ahora mismo. Recibirás las ofertas en unos minutos en tu email.';
    } else {
      document.getElementById('confirmacion').textContent =
        'De acuerdo. Mañana a las 9:00 recibirás tus ofertas personalizadas.';
    }
    showScreen('sListo');
  } catch(e) {
    msg.innerHTML = '<div class="msg err">Error: ' + e.message + '</div>';
  }
}

// PANTALLA 1 → 2 (usuario nuevo)
function irS2() {
  if (!document.getElementById('nombre').value.trim()) {
    alert('Por favor rellena el nombre.');
    return;
  }
  document.getElementById('s1').classList.remove('active');
  document.getElementById('s2').classList.add('active');
}

// PANTALLA 2 — registrar nuevo
async function registrar() {
  const btn = document.querySelector('#s2 button');
  btn.disabled = true;
  btn.textContent = 'Procesando…';
  const msg = document.getElementById('msg');
  msg.innerHTML = '';

  const payload = {
    nombre:        document.getElementById('nombre').value.trim(),
    email:         document.getElementById('email').value.trim(),
    perfil:        document.getElementById('perfil').value.trim(),
    rol_objetivo:  document.getElementById('rol').value.trim(),
    stack:         document.getElementById('stack').value.split(',').map(s=>s.trim()).filter(Boolean),
    salario_min:   parseInt(document.getElementById('salario').value) || 0,
    modalidad:     [document.getElementById('modalidad').value],
    ciudad:        document.getElementById('ciudad').value.trim(),
    linkedin:      document.getElementById('linkedin').value.trim(),
    cv_master_url: document.getElementById('cv_master_url').value.trim(),
  };

  try {
    const resp = await fetch('/registro', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (data.ok) {
      document.getElementById('confirmacion').textContent =
        data.mensaje || '¡Registro completado! En breve recibirás ofertas.';
      showScreen('sListo');
    } else {
      msg.innerHTML = '<div class="msg err">❌ ' + (data.error || 'Error inesperado') + '</div>';
      btn.disabled = false; btn.textContent = '🔍 Registrarme y buscar ahora';
    }
  } catch(e) {
    msg.innerHTML = '<div class="msg err">❌ Error de conexión: ' + e.message + '</div>';
      btn.disabled = false; btn.textContent = '🔍 Registrarme y buscar ahora';
  }
}
</script>
</body>
</html>
"""


# ══════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════

@app.route("/")
def index():
    return render_template_string(FORMULARIO_HTML)


@app.route("/health")
def health():
    return jsonify({
        "status":       "ok",
        "version":      "v2.3-groq",
        "llm_provider": "groq",
        "groq_model":   GROQ_MODEL,
        "fallbacks":    {
            "gemini":  bool(GEMINI_API_KEY),
            "claude":  bool(CLAUDE_API_KEY),
        },
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    })


@app.route("/debug")
def debug():
    """Prueba rápida del LLM activo (Groq primero)."""
    try:
        respuesta = call_llm("Responde solo: 'Groq funcionando correctamente en cv_server v2.3'")
        return jsonify({"ok": True, "respuesta": respuesta, "modelo": GROQ_MODEL})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/check-email", methods=["POST"])
def check_email():
    """Comprueba si un email ya existe en Notion. Devuelve {existe, nombre}."""
    datos = request.get_json(force=True)
    email = (datos.get("email") or "").strip().lower()
    if not email:
        return jsonify({"existe": False, "error": "email requerido"}), 400

    try:
        usuario = buscar_usuario_por_email(email)
    except Exception as e:
        logger.error("Error check-email: %s", e)
        return jsonify({"existe": False, "error": str(e)}), 500

    if usuario and usuario.get("activo"):
        return jsonify({
            "existe": True,
            "nombre": usuario.get("nombre", ""),
            "email":  email,
        })
    return jsonify({"existe": False, "email": email})


@app.route("/accion-existente", methods=["POST"])
def accion_existente():
    """Usuario existente pulsa 'Buscar ahora' o 'Mañana 9am'."""
    datos = request.get_json(force=True)
    email = (datos.get("email") or "").strip().lower()
    nombre = datos.get("nombre", "")
    accion = datos.get("accion", "")

    if not email:
        return jsonify({"ok": False, "error": "email requerido"}), 400

    if accion == "ahora" and WEBHOOK_BUSCAR_AHORA:
        try:
            requests.post(
                WEBHOOK_BUSCAR_AHORA,
                json={"email": email, "nombre": nombre},
                timeout=8,
            )
        except Exception as e:
            logger.warning("Webhook buscar-ahora falló: %s", e)

    return jsonify({"ok": True, "accion": accion, "email": email})


@app.route("/registro", methods=["POST"])
def registro():
    """Registra usuario nuevo en Notion y dispara webhook n8n."""
    datos = request.get_json(force=True)
    email = (datos.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "email requerido"}), 400

    # Si ya existe, no duplicar
    try:
        existente = buscar_usuario_por_email(email)
    except Exception:
        existente = None

    if existente:
        # Usuario ya existe → disparar búsqueda igual
        if WEBHOOK_BUSCAR_AHORA:
            try:
                requests.post(
                    WEBHOOK_BUSCAR_AHORA,
                    json={"email": email, "nombre": existente.get("nombre", "")},
                    timeout=8,
                )
            except Exception as e:
                logger.warning("Webhook buscar-ahora falló: %s", e)
        return jsonify({
            "ok": True,
            "mensaje": "Ya estabas registrado. Buscando ofertas ahora mismo.",
            "email": email,
        })

    # Crear en Notion
    try:
        notion_page = crear_usuario_en_notion(datos)
        notion_id = notion_page.get("id", "")
    except Exception as e:
        logger.error("Notion error: %s", e)
        return jsonify({"ok": False, "error": f"Error creando usuario en Notion: {e}"}), 500

    # Disparar webhook n8n nuevo-usuario (fire & forget)
    if WEBHOOK_NUEVO_USUARIO:
        try:
            requests.post(WEBHOOK_NUEVO_USUARIO, json={**datos, "notion_id": notion_id}, timeout=8)
        except Exception as e:
            logger.warning("Webhook nuevo-usuario falló (no crítico): %s", e)

    return jsonify({
        "ok":      True,
        "mensaje": "Usuario registrado. En breve recibirás ofertas de trabajo.",
        "email":   email,
    })


@app.route("/generar-cv", methods=["POST"])
def generar_cv():
    """Genera un CV personalizado con CV master real y lo sube a Drive."""
    datos = request.get_json(force=True)
    email       = datos.get("email", "")
    empresa     = datos.get("empresa", "")
    puesto      = datos.get("puesto", "")
    descripcion = datos.get("descripcion", "")

    if not email or not empresa or not puesto:
        return jsonify({"ok": False, "error": "email, empresa y puesto son requeridos"}), 400

    # 1. Leer perfil completo del usuario desde Notion
    usuario = buscar_usuario_por_email(email)
    if not usuario:
        return jsonify({"ok": False, "error": f"Usuario {email} no encontrado en Notion"}), 404

    nombre = usuario.get("nombre") or email.split("@")[0]

    # 2. Detectar idioma de la oferta y leer el CV master en ese idioma
    idioma = detectar_idioma(puesto, descripcion, empresa)
    tiene_master_configurado = _tiene_algun_master(usuario)
    cv_master = leer_cv_master_desde_drive(usuario, idioma)

    # Guardrail: si hay un master configurado pero lo leído es ilegible
    # (basura binaria de un .docx sin parsear, o sin acceso), NO generamos
    # nada. Mejor fallar claro que mandar un CV con datos inventados.
    def _es_legible(t: str) -> bool:
        if not t:
            return False
        if t.lstrip().startswith("PK"):  # firma ZIP de un .docx no parseado
            return False
        imprimibles = sum(1 for c in t if c.isprintable() or c in "\n\r\t")
        return imprimibles / len(t) >= 0.85

    if tiene_master_configurado and not _es_legible(cv_master):
        logger.error("CV master ILEGIBLE para %s (largo=%d) — abortando para no inventar",
                     email, len(cv_master or ""))
        return jsonify({
            "ok": False,
            "error": ("No se pudo leer tu CV master desde Drive (archivo ilegible o sin acceso). "
                      "NO se generó un CV para evitar enviar datos inventados. "
                      "Revisá el archivo y los permisos en Drive."),
        }), 502

    if cv_master:
        logger.info("CV master leído (%d chars) para %s", len(cv_master), email)
    else:
        logger.warning("CV master no encontrado para %s — usando solo perfil de Notion", email)

    # 3. Construir contexto del candidato
    ciudad = usuario.get("ciudad", "Madrid")
    rol    = usuario.get("rol", "")
    stack  = ", ".join(usuario.get("stack", [])) or "React, TypeScript"

    # 4. Prompt con 4 fases + CV master real
    if cv_master:
        contexto_candidato = f"""CV MASTER COMPLETO (usa SOLO esta experiencia, NO inventes):
{cv_master}"""
    else:
        contexto_candidato = f"""PERFIL DEL CANDIDATO (sin CV master disponible):
- Nombre: {nombre}
- Rol objetivo: {rol}
- Stack: {stack}
- Ciudad: {ciudad}
- Perfil: {usuario.get("perfil", "")}"""

    # Titulos de seccion y regla de idioma, en el idioma de la oferta
    idioma_nombre = "English" if idioma == "en" else "Spanish"
    if idioma == "en":
        bloque_formato = """OUTPUT FORMAT (plain text, no markdown):

HEADLINE: [professional title for this offer — see HEADLINE RULES below]

PROFESSIONAL SUMMARY
[2 full paragraphs (4-6 lines each) tailored to the offer, based on the CV master summary. First paragraph: who she is + core strengths relevant to this role. Second paragraph: depth, domains and the angle that fits this offer.]

PROFESSIONAL EXPERIENCE
[Company] — [City]
[Role]
[Start date] – [End date]
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
(6-9 bullets for recent/relevant roles, 3-4 for older ones — always real, never padded)

TECHNICAL SKILLS
[Skills grouped by category (Frontend, AI, Design Systems, Backend, Cloud, Testing...) with concrete tools/versions, ordered by relevance to this offer]

EDUCATION
[From the CV master]

LANGUAGES
[From the CV master]

FINAL RULES:
- First line MUST be "HEADLINE: ..." — it becomes the header title
- Do NOT include name/email/phone, they are added programmatically
- Do NOT use markdown (**text**, ##, ```)
- Do NOT invent anything not in the CV master
- Language: the ENTIRE CV must be in English (section titles and content)"""
    else:
        bloque_formato = """FORMATO DE SALIDA (texto plano, sin markdown):

HEADLINE: [titular profesional para esta oferta — ver REGLAS DEL HEADLINE abajo]

PERFIL PROFESIONAL
[2 párrafos completos (4-6 líneas cada uno) adaptados a la oferta, basados en el resumen del CV master. Primer párrafo: quién es + fortalezas clave relevantes para este puesto. Segundo párrafo: profundidad, dominios y el ángulo que encaja con esta oferta.]

EXPERIENCIA PROFESIONAL
[Empresa] — [Ciudad]
[Puesto]
[Fecha inicio] – [Fecha fin]
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
(6-9 bullets en los puestos recientes/relevantes, 3-4 en los antiguos — siempre reales, nunca de relleno)

HABILIDADES TÉCNICAS
[Skills agrupadas por categoría (Frontend, IA, Sistemas de Diseño, Backend, Cloud, Testing...) con herramientas/versiones concretas, ordenadas por relevancia para esta oferta]

FORMACIÓN
[Del CV master]

IDIOMAS
[Del CV master]

REGLAS FINALES:
- La primera línea DEBE ser "HEADLINE: ..." — se usa como titular de la cabecera
- NO incluir nombre/email/tel, se añaden programáticamente
- NO usar markdown (**texto**, ##, ```)
- NO inventar nada que no esté en el CV master
- Idioma: TODO el CV en español (títulos de sección y contenido)"""

    prompt = f"""Act as a senior tech recruiter who screens 200+ CVs daily. Adapt this candidate's CV for a specific job offer.

The target job offer is written in {idioma_nombre}. Generate the ENTIRE CV in {idioma_nombre} — both the section titles and the content.

{contexto_candidato}

OFERTA TARGET:
- Empresa: {empresa}
- Puesto: {puesto}
- Descripción: {descripcion or "No disponible"}

PASO 1 — ANÁLISIS INTERNO (no mostrar en output):
- Skills del CV master que encajan con esta oferta
- Keywords de la oferta que deben aparecer
- Logros que mejor demuestran el fit
- NO inventar experiencia, métricas ni logros

PASO 2 — CV ADAPTADO (output principal):
Genera el CV adaptado con estas reglas ESTRICTAS:
1. USA SOLO experiencia real del CV master, NO inventar métricas ni logros
2. Adapta el ORDEN y ÉNFASIS según la oferta, no el contenido
3. Keywords de la oferta integradas honestamente
4. Bullets con fórmula XYZ ("Logré X, medido por Y, haciendo Z") SIEMPRE que los datos lo permitan — nada de bullets genéricos tipo "responsable de..."
5. Densidad real: NO recortes ni resumas el CV master. Los puestos recientes/relevantes deben llevar 6-9 bullets; los antiguos 3-4. Si el master tiene el detalle, úsalo entero.
6. Máximo 2 páginas

HEADLINE RULES (primera línea del output):
- Base canónica: "Full-Stack Developer & AI Engineer" (Full-Stack primero, IA después)
- AJUSTA el titular al ángulo VERAZ de la oferta: si la oferta es de frontend → "Frontend Developer"; si es full-stack → la base; si está centrada en IA → "AI Engineer" al frente
- NUNCA un rol que la candidata no tiene (p.ej. JAMÁS "Video Editor" ni similares). Si la oferta pide un rol que no encaja con su perfil real, usa la base canónica
- El titular va en el idioma de la oferta

PASO 3 — REVISION ANTI-IA (aplicar al output antes de entregar):
Elimina TODO rastro de texto generado por IA:
- Cero guiones largos (—) ni dobles guiones (--)
- Cero frases tipo "responsable de...", "encargada de...", "orientada a..."
- Cero adjetivos vacíos ("dinámico", "proactivo", "apasionado", "motivado")
- Cero "passionate about", "I'd love to", "excited to"
- Cero verbos pasivos innecesarios ("fue responsable de..." → "lideró...")
- Si suena a IA, reescríbelo con lenguaje humano y directo
- Mantener tono profesional pero natural, como lo escribiría una persona

{bloque_formato}"""

    try:
        # Claude (calidad) primario; Groq de fallback dentro de call_llm_calidad
        contenido_cv = call_llm_calidad(prompt, model=CV_MODEL, max_tokens=4096)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 503

    # 5. Limpiar output del LLM y extraer el titular (HEADLINE)
    titular = ""
    lineas_limpias = []
    for linea in contenido_cv.split("\n"):
        limpia = linea.strip().replace("**", "").replace("`", "").replace("##", "").replace("# ", "")
        # Titular generado por el LLM (primera línea HEADLINE) → cabecera, fuera del cuerpo
        if not titular and limpia.lower().startswith("headline:"):
            titular = limpia.split(":", 1)[1].strip()
            continue
        # Filtrar frases introductorias del LLM
        if limpia.lower().startswith(("aquí", "here is", "here's", "a continuación", "claro", "por supuesto")):
            continue
        lineas_limpias.append(limpia)
    contenido_cv = "\n".join(lineas_limpias)

    # 6. Generar DOCX con cabecera estructurada (titular adaptado por la oferta)
    nombre_archivo = _nombre_archivo_cv(nombre, puesto)
    docx_bytes = generar_docx_con_cabecera(contenido_cv, usuario, titular)

    # 7. Subir a Drive
    try:
        link_drive = subir_cv_a_drive(docx_bytes, nombre_archivo)
    except Exception as e:
        logger.error("Drive upload error: %s", e)
        return jsonify({"ok": False, "error": f"Error subiendo a Drive: {e}"}), 500

    return jsonify({
        "ok":              True,
        "link":            link_drive,
        "modelo_usado":    GROQ_MODEL,
        "archivo":         nombre_archivo,
        "email":           email,
        "cv_master_usado": bool(cv_master),
        "idioma":          idioma,
        "cv_master_url":   usuario.get("cv_master_url", "") or "",
    })


@app.route("/generar-carta", methods=["POST"])
def generar_carta():
    """Genera la carta de presentación con la experiencia real del CV master.
    Usa Claude Sonnet (calidad) — la carta va a la empresa."""
    datos = request.get_json(force=True)
    email       = datos.get("email", "")
    empresa     = datos.get("empresa", "")
    puesto      = datos.get("puesto", "")
    descripcion = datos.get("descripcion", "")

    if not email or not empresa or not puesto:
        return jsonify({"ok": False, "error": "email, empresa y puesto son requeridos"}), 400

    usuario = buscar_usuario_por_email(email)
    if not usuario:
        return jsonify({"ok": False, "error": f"Usuario {email} no encontrado en Notion"}), 404

    nombre = usuario.get("nombre") or email.split("@")[0]

    # Detectar idioma de la oferta y leer el CV master en ese idioma
    idioma = detectar_idioma(puesto, descripcion, empresa)
    tiene_master = _tiene_algun_master(usuario)
    cv_master = leer_cv_master_desde_drive(usuario, idioma)

    def _es_legible(t: str) -> bool:
        if not t:
            return False
        if t.lstrip().startswith("PK"):
            return False
        imprimibles = sum(1 for c in t if c.isprintable() or c in "\n\r\t")
        return imprimibles / len(t) >= 0.85

    if tiene_master and not _es_legible(cv_master):
        logger.error("CV master ILEGIBLE para carta de %s — abortando", email)
        return jsonify({
            "ok": False,
            "error": ("No se pudo leer tu CV master desde Drive. NO se generó la carta "
                      "para evitar inventar datos. Revisá el archivo y permisos en Drive."),
        }), 502

    contexto = (f"CV MASTER (usa SOLO esta experiencia real, NO inventes nada):\n{cv_master}"
                if cv_master else
                f"PERFIL: {nombre} — {usuario.get('rol','')} — {usuario.get('perfil','')}")

    prompt = f"""Eres un experto en cartas de presentación para ofertas de trabajo.
Escribe una carta de presentación profesional para {nombre}.

{contexto}

OFERTA:
- Empresa: {empresa}
- Puesto: {puesto}
- Descripción: {descripcion or "No disponible"}

REGLAS:
- La oferta está en {"inglés" if idioma == "en" else "español"}. Escribe TODA la carta en ese idioma (saludo, cuerpo y despedida).
- Máximo 250 palabras.
- Usa SOLO experiencia real del CV master; conecta esa experiencia con lo que pide la oferta. NO inventes.
- Tono profesional, directo y humano. Cero frases vacías de IA: nada de "apasionada",
  "proactiva", "soluciones innovadoras", "emocionada de la oportunidad", "dinámica".
- Menciona logros o tecnologías concretas del CV que encajen con la oferta.
- Formato carta: saludo formal ("Estimados/as," en español, "Dear Hiring Team," en inglés) ... cuerpo ... despedida formal ("Atentamente," / "Sincerely,") seguida de "{nombre}".
- Devuelve SOLO el texto de la carta, sin encabezados ni comentarios."""

    try:
        carta = call_llm_calidad(prompt, model=CARTA_MODEL, max_tokens=1500)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 503

    # Limpiar frases introductorias del LLM
    carta = carta.strip()
    for pref in ("aquí tienes", "aquí está", "here is", "here's", "claro", "por supuesto"):
        if carta.lower().startswith(pref):
            carta = carta.split("\n", 1)[-1].strip()
            break

    return jsonify({
        "ok":              True,
        "carta":           carta,
        "modelo_usado":    CARTA_MODEL,
        "email":           email,
        "cv_master_usado": bool(cv_master),
    })


@app.route("/usuarios", methods=["GET"])
def usuarios():
    """Consulta usuarios activos en Notion."""
    if not NOTION_DB_USUARIOS:
        return jsonify({"ok": False, "error": "NOTION_DB_USUARIOS no configurada"}), 500
    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}/query",
            headers=notion_headers(),
            json={"filter": {"property": "Activo", "checkbox": {"equals": True}}},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        usuarios_list = []
        for p in results:
            props = p.get("properties", {})
            usuarios_list.append({
                "id":     p["id"],
                "nombre": props.get("Name", {}).get("title", [{}])[0].get("plain_text", ""),
                "email":  props.get("Email", {}).get("email", ""),
                "activo": props.get("Activo", {}).get("checkbox", False),
            })
        return jsonify({"ok": True, "usuarios": usuarios_list, "total": len(usuarios_list)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/buscar-ofertas-reales", methods=["POST"])
def buscar_ofertas_reales_endpoint():
    """
    Busca ofertas REALES en Remotive (sustituye al LLM inventando ofertas).

    Body esperado:
    {
        "rol": "frontend developer",        // opcional, default del perfil
        "stack": ["react", "typescript"],    // opcional
        "modalidad": ["Remoto"],             // opcional
        "ciudad": "Madrid",                  // opcional
    }
    """
    datos = request.get_json(force=True)
    perfil = datos.get("perfil", "")
    rol = datos.get("rol", "")
    stack = datos.get("stack", [])
    modalidad = datos.get("modalidad", [])
    ciudad = datos.get("ciudad", "")
    salario_min = datos.get("salario_min", 0)
    top_n = datos.get("top_n", 5)

    try:
        ofertas = buscar_ofertas_reales(perfil=perfil, rol=rol, stack=stack, salario_min=salario_min, modalidad=modalidad, ciudad=ciudad, top_n=top_n)
        return jsonify({"ok": True, "ofertas": ofertas, "total": len(ofertas)})
    except Exception as e:
        logger.error("Error buscando ofertas reales: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)