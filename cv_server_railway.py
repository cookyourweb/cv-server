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
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # default razonable

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


def buscar_usuario_por_email(email: str) -> dict | None:
    """Consulta Notion por email. Devuelve datos del usuario o None."""
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
    props = page.get("properties", {})
    return {
        "notion_id": page.get("id", ""),
        "nombre":    (props.get("Name", {}).get("title") or [{}])[0].get("plain_text", ""),
        "email":     props.get("Email", {}).get("email", ""),
        "activo":    props.get("Activo", {}).get("checkbox", False),
    }


def crear_usuario_en_notion(datos: dict) -> dict:
    """Crea un usuario en la BD de Notion."""
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": NOTION_DB_USUARIOS},
        "properties": {
            "Name":           {"title":  [{"text": {"content": datos.get("nombre", "")}}]},
            "Email":          {"email":   datos.get("email", "")},
            "Perfil":         {"rich_text": [{"text": {"content": datos.get("perfil", "")}}]},
            "Rol objetivo":   {"rich_text": [{"text": {"content": datos.get("rol_objetivo", "") or datos.get("rol", "")}}]},
            "Stack":          {"multi_select": [{"name": s} for s in datos.get("stack", [])]},
            "Salario min":    {"number": datos.get("salario_min") or datos.get("salario") or 0},
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
    """Genera un CV personalizado con LLM y lo sube a Drive."""
    datos = request.get_json(force=True)
    email   = datos.get("email", "")
    empresa = datos.get("empresa", "")
    puesto  = datos.get("puesto", "")
    perfil  = datos.get("perfil", "")
    nombre  = datos.get("nombre", email.split("@")[0] if email else "candidato")

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
        "ok":           True,
        "link":         link_drive,
        "modelo_usado": GROQ_MODEL,
        "archivo":      nombre_archivo,
        "email":        email,
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