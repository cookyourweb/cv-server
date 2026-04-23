#!/usr/bin/env python3
"""
cv_server_railway.py  —  v2.3-groq
LLM: Groq (primario) → Gemini (fallback) → Claude (fallback)
Todo lo demás sin cambios: formulario, Notion, DOCX, Drive, webhooks n8n.
"""

import os
import io
import json
import logging
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

# Google Drive / OAuth
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# DOCX
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ─────────────────────────────────────────────
# CONFIGURACIÓN — solo variables de entorno
# ─────────────────────────────────────────────

# ── LLM: Groq (primario) ──────────────────────
GROQ_API_KEY = os.environ["GROQ_API_KEY"]                          # requerido
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile") # default razonable

# ── LLM: Gemini (fallback opcional) ──────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# ── LLM: Claude (fallback opcional) ──────────
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")

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


# ══════════════════════════════════════════════
# NOTION
# ══════════════════════════════════════════════

def notion_headers():
    return {
        "Authorization":  f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json",
    }


def crear_usuario_en_notion(datos: dict) -> dict:
    """Crea o actualiza un usuario en la BD de Notion."""
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": NOTION_DB_USUARIOS},
        "properties": {
            "Name":           {"title":  [{"text": {"content": datos.get("nombre", "")}}]},
            "Email":          {"email":   datos.get("email", "")},
            "Perfil":         {"rich_text": [{"text": {"content": datos.get("perfil", "")}}]},
            "Rol objetivo":   {"rich_text": [{"text": {"content": datos.get("rol", "")}}]},
            "Stack":          {"multi_select": [{"name": s} for s in datos.get("stack", [])]},
            "Salario min":    {"number": datos.get("salario", 0)},
            "Modalidad":      {"multi_select": [{"name": m} for m in datos.get("modalidad", [])]},
            "Ciudad":         {"rich_text": [{"text": {"content": datos.get("ciudad", "")}}]},
            "LinkedIn":       {"url": datos.get("linkedin") or None},
            "CV Master URL":  {"url": datos.get("cv_master_url") or None},
            "Activo":         {"checkbox": True},
        },
    }
    resp = requests.post(url, headers=notion_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ══════════════════════════════════════════════
# GENERACIÓN DOCX
# ══════════════════════════════════════════════

def generar_docx(contenido_cv: str, nombre_candidato: str) -> bytes:
    doc = Document()

    # Título
    titulo = doc.add_heading(nombre_candidato, level=1)
    titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in titulo.runs:
        run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)

    doc.add_paragraph()

    # Contenido generado por LLM (texto plano con secciones por líneas)
    for linea in contenido_cv.split("\n"):
        linea = linea.strip()
        if not linea:
            doc.add_paragraph()
            continue
        if linea.startswith("##"):
            h = doc.add_heading(linea.lstrip("# "), level=2)
            for run in h.runs:
                run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)
        elif linea.startswith("#"):
            doc.add_heading(linea.lstrip("# "), level=1)
        else:
            p = doc.add_paragraph(linea)
            p.style.font.size = Pt(11)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ══════════════════════════════════════════════
# FORMULARIO HTML (sin cambios)
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
    .msg { margin-top: 1rem; padding: .75rem; border-radius: 8px; font-size: .9rem; }
    .ok  { background: #d1fae5; color: #065f46; }
    .err { background: #fee2e2; color: #991b1b; }
    .step { color: #9ca3af; font-size: .8rem; margin-bottom: 1rem; }
  </style>
</head>
<body>
<div class="card">
  <h1>🚀 BuscarTrabajo.ai</h1>
  <p class="sub">Encuentra trabajo con IA — rellena tu perfil y nosotros buscamos por ti.</p>

  <!-- PANTALLA 1 — Datos básicos -->
  <div id="s1" class="screen active">
    <p class="step">Paso 1 de 2</p>
    <label>Nombre completo</label>
    <input id="nombre" placeholder="Ana García López" />
    <label>Email</label>
    <input id="email" type="email" placeholder="ana@ejemplo.com" />
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
    <button type="button" onclick="registrar()">🔍 Buscar ahora</button>
    <div id="msg"></div>
  </div>
</div>

<script>
function irS2() {
  if (!document.getElementById('nombre').value.trim() ||
      !document.getElementById('email').value.trim()) {
    alert('Por favor rellena nombre y email.');
    return;
  }
  document.getElementById('s1').classList.remove('active');
  document.getElementById('s2').classList.add('active');
}

async function registrar() {
  const btn = document.querySelector('#s2 button');
  btn.disabled = true;
  btn.textContent = 'Procesando…';
  const msg = document.getElementById('msg');
  msg.innerHTML = '';

  const payload = {
    nombre:       document.getElementById('nombre').value.trim(),
    email:        document.getElementById('email').value.trim(),
    perfil:       document.getElementById('perfil').value.trim(),
    rol_objetivo: document.getElementById('rol').value.trim(),
    stack:        document.getElementById('stack').value.split(',').map(s=>s.trim()).filter(Boolean),
    salario_min:  parseInt(document.getElementById('salario').value) || 0,
    modalidad:    [document.getElementById('modalidad').value],
    ciudad:       document.getElementById('ciudad').value.trim(),
    linkedin:     document.getElementById('linkedin').value.trim(),
  };

  try {
    const resp = await fetch('/registro', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (data.ok) {
      msg.innerHTML = '<div class="msg ok">✅ ' + (data.mensaje || '¡Registro completado! En breve recibirás ofertas.') + '</div>';
    } else {
      msg.innerHTML = '<div class="msg err">❌ ' + (data.error || 'Error inesperado') + '</div>';
      btn.disabled = false; btn.textContent = '🔍 Buscar ahora';
    }
  } catch(e) {
    msg.innerHTML = '<div class="msg err">❌ Error de conexión: ' + e.message + '</div>';
    btn.disabled = false; btn.textContent = '🔍 Buscar ahora';
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
        "timestamp":    datetime.utcnow().isoformat() + "Z",
    })


@app.route("/debug")
def debug():
    """Prueba rápida del LLM activo (Groq primero)."""
    try:
        respuesta = call_llm("Responde solo: 'Groq funcionando correctamente en cv_server v2.3'")
        return jsonify({"ok": True, "respuesta": respuesta, "modelo": GROQ_MODEL})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/registro", methods=["POST"])
def registro():
    """Registra usuario en Notion y dispara webhook n8n."""
    datos = request.get_json(force=True)
    if not datos.get("email"):
        return jsonify({"ok": False, "error": "email requerido"}), 400

    try:
        notion_page = crear_usuario_en_notion(datos)
        notion_id = notion_page.get("id", "")
    except Exception as e:
        logger.error("Notion error: %s", e)
        return jsonify({"ok": False, "error": f"Error creando usuario en Notion: {e}"}), 500

    # Disparar webhook n8n (fire & forget)
    if WEBHOOK_NUEVO_USUARIO:
        try:
            requests.post(WEBHOOK_NUEVO_USUARIO, json={**datos, "notion_id": notion_id}, timeout=8)
        except Exception as e:
            logger.warning("Webhook nuevo-usuario falló (no crítico): %s", e)

    return jsonify({
        "ok":      True,
        "mensaje": "Usuario registrado. En breve recibirás ofertas de trabajo.",
        "email":   datos.get("email"),
    })


@app.route("/generar-cv", methods=["POST"])
def generar_cv():
    """Genera un CV personalizado con LLM y lo sube a Drive."""
    datos = request.get_json(force=True)
    email   = datos.get("email", "")
    empresa = datos.get("empresa", "")
    puesto  = datos.get("puesto", "")
    perfil  = datos.get("perfil", "")
    nombre  = datos.get("nombre", email.split("@")[0])

    if not email or not empresa or not puesto:
        return jsonify({"ok": False, "error": "email, empresa y puesto son requeridos"}), 400

    # Prompt para el LLM
    prompt = f"""Eres un experto redactor de CVs para el mercado español.
Genera un CV profesional y conciso para el candidato siguiente, adaptado a la oferta.

CANDIDATO:
- Nombre: {nombre}
- Perfil: {perfil}

OFERTA:
- Empresa: {empresa}
- Puesto: {puesto}

Formato de salida (usa ## para secciones):
## Perfil profesional
(2-3 frases impactantes)

## Experiencia relevante
(lista de logros adaptados al puesto)

## Habilidades clave
(lista concisa)

## Formación
(breve)

Sé directo, usa lenguaje activo, adapta el CV al puesto. Máximo 400 palabras."""

    try:
        contenido_cv = call_llm(prompt)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 503

    # Generar DOCX
    nombre_archivo = f"CV_{nombre.replace(' ', '_')}_{empresa.replace(' ', '_')}.docx"
    docx_bytes = generar_docx(contenido_cv, nombre)

    # Subir a Drive
    try:
        link_drive = subir_cv_a_drive(docx_bytes, nombre_archivo)
    except Exception as e:
        logger.error("Drive upload error: %s", e)
        return jsonify({"ok": False, "error": f"Error subiendo a Drive: {e}"}), 500

    return jsonify({
        "ok":          True,
        "link":        link_drive,
        "modelo_usado": GROQ_MODEL,
        "archivo":     nombre_archivo,
        "email":       email,
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


# ══════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)