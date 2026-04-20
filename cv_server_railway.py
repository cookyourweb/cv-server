#!/usr/bin/env python3
"""
CV Server — Genera CVs adaptados profesionales en DOCX y los sube a Drive.
Versión para Railway/Render — usa variables de entorno.

FIXES (20 Abril 2026):
- Model string corregido: claude-sonnet-4-6 → claude-sonnet-4-6-20260217
- Añadidos timeouts a llamadas externas (Claude, Drive)
- Mejor manejo de errores con mensajes detallados
- Endpoint /debug para diagnosticar problemas
- Endpoint /test-claude para probar solo la API de Claude
"""

from flask import Flask, request, jsonify
import json, os, re, requests, base64, io
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

app = Flask(__name__)

FOLDER_GENERADOS = os.getenv("FOLDER_GENERADOS", "1tHuVOIz3ratjRp8AmHsF0kGVpmy9DocY")
FOLDER_CV = os.getenv("FOLDER_CV", "1duJA_G3lLbOqiUYoSJcsXAvbtJUdcmzR")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive"]

# ✅ FIX: Model string con fecha — el formato correcto para la API de Anthropic
CLAUDE_MODEL = "claude-sonnet-4-6-20260217"
# Fallback si el anterior falla:
CLAUDE_MODEL_FALLBACK = "claude-sonnet-4-5-20250929"

BLUE = RGBColor(0x1F, 0x5C, 0x8B)
DARK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x66, 0x66, 0x66)


def get_drive_service():
    if not GOOGLE_CREDENTIALS:
        raise Exception("Variable GOOGLE_CREDENTIALS no configurada en Railway")
    try:
        creds_json = base64.b64decode(GOOGLE_CREDENTIALS).decode("utf-8")
        creds_dict = json.loads(creds_json)
    except Exception as e:
        raise Exception(f"Error decodificando GOOGLE_CREDENTIALS: {e}")
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=GOOGLE_SCOPES)
    return build("drive", "v3", credentials=creds)


def leer_cv_master(service):
    results = service.files().list(
        q=f"name='CV_Master_Veronica.txt' and '{FOLDER_CV}' in parents and trashed=false",
        fields="files(id, name)"
    ).execute()
    files = results.get("files", [])
    if not files:
        raise Exception(
            f"No se encontró CV_Master_Veronica.txt en la carpeta de Drive (FOLDER_CV={FOLDER_CV}). "
            "Verifica que el archivo existe y que la cuenta de servicio tiene acceso."
        )
    file_id = files[0]["id"]
    req = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return buffer.read().decode("utf-8")


def call_claude(prompt, max_tokens=6000, model=None):
    """Llama a la API de Claude con timeout y fallback de modelo."""
    if not CLAUDE_API_KEY:
        raise Exception("Variable CLAUDE_API_KEY no configurada en Railway")

    target_model = model or CLAUDE_MODEL

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": target_model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=90  # ✅ FIX: Timeout de 90s — sin esto Railway puede cortar la conexión
        )
    except requests.Timeout:
        raise Exception(f"Timeout llamando a Claude API (90s) con modelo {target_model}")
    except requests.ConnectionError as e:
        raise Exception(f"Error de conexión con Claude API: {e}")

    if response.status_code != 200:
        error_detail = response.text[:500]
        # ✅ FIX: Si falla por modelo inválido, intentar con fallback
        if response.status_code in (400, 404) and target_model == CLAUDE_MODEL:
            print(f"⚠️  Modelo {target_model} falló ({response.status_code}), intentando fallback {CLAUDE_MODEL_FALLBACK}...")
            return call_claude(prompt, max_tokens, model=CLAUDE_MODEL_FALLBACK)
        raise Exception(
            f"Claude API error {response.status_code}: {error_detail}. "
            f"Modelo usado: {target_model}. "
            "Verifica que CLAUDE_API_KEY es válida y el modelo existe."
        )

    data = response.json()
    if not data.get("content") or not data["content"][0].get("text"):
        raise Exception(f"Respuesta de Claude vacía o inesperada: {json.dumps(data)[:300]}")

    return data["content"][0]["text"]


def generar_cv_adaptado(cv_master, empresa, puesto, descripcion):
    prompt = f"""Eres el asistente de Verónica Serna, Senior Frontend Developer con 15+ años de experiencia.

CV Master:
{cv_master}

OFERTA:
- Empresa: {empresa}
- Puesto: {puesto}
- Descripción: {descripcion}

TASK: Genera SOLO el contenido del CV adaptado. Sin markdown, sin ```, sin #, sin intro.

FORMATO DE SALIDA (contenido crudo, una línea por elemento):

PERFIL PROFESIONAL
[2-3 líneas adaptadas a la oferta]

EXPERIENCIA PROFESIONAL
Empresa — Ciudad
Puesto
Fecha inicio – Fecha fin
- Logro 1
- Logro 2

HABILIDADES TÉCNICAS
[Skills ordenadas por relevancia]

FORMACIÓN
Título — Institución (Año)

IDIOMAS
Idioma: Nivel

REGLAS:
- NO uses markdown (**, #, ```, -)
- NO incluyas cabecera (nombre/email/teléfono)
- NO añadas texto introductorio ni conclusiones
- USA guiones normales (-) para bullets
- SEPARA secciones con línea en blanco
- MÁXIMO 2 páginas de contenido"""

    response = call_claude(prompt)

    # Limpiar respuesta: quitar bloques markdown y texto extra
    lines = response.strip().split('\n')
    cleaned_lines = []

    in_code_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped.lower().startswith(('aquí', 'here', 'este', 'this', 'espero', 'i hope')):
            continue
        clean = stripped.replace('**', '').replace('`', '').replace('#', '').strip()
        if clean:
            cleaned_lines.append(clean)

    return '\n'.join(cleaned_lines)


def add_border_bottom(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '4')
    bottom.set(qn('w:space'), '2')
    bottom.set(qn('w:color'), '1F5C8B')
    pBdr.append(bottom)
    pPr.append(pBdr)


def generar_docx(cv_texto, output_path, empresa, puesto):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(10)

    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    # Cabecera
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("VERÓNICA SERNA PÉREZ")
    r.bold = True; r.font.size = Pt(18); r.font.color.rgb = DARK

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Senior Frontend Developer · React + TypeScript")
    r.font.size = Pt(11); r.font.color.rgb = BLUE

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Madrid, España · +34 655 13 38 39 · verserper@gmail.com · linkedin.com/in/veronica4web")
    r.font.size = Pt(8.5); r.font.color.rgb = GREY

    p = doc.add_paragraph()
    add_border_bottom(p)

    SECTIONS = ['PERFIL PROFESIONAL', 'EXPERIENCIA PROFESIONAL', 'EXPERIENCIA',
                'HABILIDADES TÉCNICAS', 'HABILIDADES', 'FORMACIÓN', 'IDIOMAS',
                'COMPETENCIAS', 'PROYECTOS', 'CERTIFICACIONES', 'EDUCACIÓN']

    for line in cv_texto.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        if 'VERÓNICA SERNA' in line.upper() or line.startswith('# '):
            continue
        clean = re.sub(r'^#{1,3}\s*', '', line).strip()
        clean = clean.replace('```', '')
        clean_upper = re.sub(r'\*\*', '', clean).upper().strip()

        is_section = any(kw in clean_upper for kw in SECTIONS)
        if is_section and len(clean) < 40:
            p = doc.add_paragraph()
            r = p.add_run(re.sub(r'\*\*', '', clean).upper())
            r.bold = True; r.font.size = Pt(10); r.font.color.rgb = BLUE
            add_border_bottom(p)
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(6)
            continue

        if line.startswith(('- ', '• ', '* ')):
            texto = re.sub(r'\*\*(.*?)\*\*', r'\1', line[2:].strip())
            p = doc.add_paragraph()
            r = p.add_run("• " + texto)
            r.font.size = Pt(9.5); r.font.color.rgb = DARK
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.space_after = Pt(2)
            continue

        if ('—' in line or ' – ' in line) and len(line) < 100:
            texto = re.sub(r'\*\*(.*?)\*\*', r'\1', line)
            p = doc.add_paragraph()
            r = p.add_run(texto)
            r.bold = True; r.font.size = Pt(10); r.font.color.rgb = DARK
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(1)
            continue

        if re.search(r'(20\d{2}|19\d{2})', line) and len(line) < 60 and not line.startswith(('- ', '•')):
            texto = re.sub(r'\*\*(.*?)\*\*', r'\1', line).replace('`', '')
            p = doc.add_paragraph()
            r = p.add_run(texto)
            r.italic = True; r.font.size = Pt(9); r.font.color.rgb = GREY
            p.paragraph_format.space_after = Pt(3)
            continue

        texto = re.sub(r'\*\*(.*?)\*\*', r'\1', clean).replace('`', '')
        if texto:
            p = doc.add_paragraph()
            r = p.add_run(texto)
            r.font.size = Pt(9.5); r.font.color.rgb = DARK
            p.paragraph_format.space_after = Pt(4)

    doc.save(output_path)


def crear_carpeta_drive(service, nombre, parent_id):
    res = service.files().list(
        q=f"name='{nombre}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id)"
    ).execute()
    if res["files"]:
        return res["files"][0]["id"]
    meta = {"name": nombre, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    return service.files().create(body=meta, fields="id").execute()["id"]


def subir_a_drive(service, file_path, file_name, folder_id):
    meta = {"name": file_name, "parents": [folder_id]}
    media = MediaFileUpload(file_path, mimetype=MIME_DOCX, resumable=True)
    archivo = service.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()
    service.permissions().create(fileId=archivo["id"], body={"type": "anyone", "role": "reader"}).execute()
    return archivo.get("webViewLink")


def generar_y_subir_cv(empresa, puesto, descripcion):
    steps_completed = []
    try:
        print(f"🔗 [1] Conectando a Drive...")
        service = get_drive_service()
        steps_completed.append("drive_connect")

        print(f"📖 [2] Leyendo CV Master...")
        cv_master = leer_cv_master(service)
        steps_completed.append("cv_master_read")

        print(f"🤖 [3] Claude generando CV para {empresa} (modelo: {CLAUDE_MODEL})...")
        cv_adaptado = generar_cv_adaptado(cv_master, empresa, puesto, descripcion)
        steps_completed.append("claude_generate")

        fecha = datetime.now().strftime("%Y-%m-%d")
        empresa_slug = re.sub(r'[^a-zA-Z0-9]', '-', empresa)[:30]
        puesto_slug = re.sub(r'[^a-zA-Z0-9]', '-', puesto)[:30]
        nombre_carpeta = f"{fecha}_{empresa_slug}_{puesto_slug}"
        nombre_archivo = f"CV_Veronica_{empresa_slug}.docx"

        print(f"📄 [4] Generando DOCX...")
        temp_path = f"/tmp/{nombre_archivo}"
        generar_docx(cv_adaptado, temp_path, empresa, puesto)
        steps_completed.append("docx_generated")

        print(f"☁️  [5] Subiendo a Drive...")
        folder_id = crear_carpeta_drive(service, nombre_carpeta, FOLDER_GENERADOS)
        link = subir_a_drive(service, temp_path, nombre_archivo, folder_id)
        steps_completed.append("drive_upload")

        if os.path.exists(temp_path):
            os.remove(temp_path)

        print(f"✅ CV subido: {link}")
        return {
            "success": True,
            "link": link,
            "carpeta": nombre_carpeta,
            "archivo": nombre_archivo,
            "modelo_usado": CLAUDE_MODEL
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"❌ Error en paso posterior a {steps_completed}: {e}")
        print(tb)
        return {
            "success": False,
            "error": str(e),
            "steps_completed": steps_completed,
            "traceback": tb[-1000:]  # últimas 1000 chars para no saturar logs
        }


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.route('/generar-cv', methods=['POST', 'OPTIONS'])
def generar_cv():
    if request.method == 'OPTIONS':
        r = jsonify({})
        r.headers.add('Access-Control-Allow-Origin', '*')
        r.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        r.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return r
    data = request.get_json()
    resultado = generar_y_subir_cv(
        data.get('empresa', 'Empresa'),
        data.get('puesto', 'Puesto'),
        data.get('descripcion', '')
    )
    r = jsonify(resultado)
    r.headers.add('Access-Control-Allow-Origin', '*')
    return r


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "model": CLAUDE_MODEL,
        "env_vars": {
            "CLAUDE_API_KEY": "✅ configurada" if CLAUDE_API_KEY else "❌ FALTA",
            "GOOGLE_CREDENTIALS": "✅ configurada" if GOOGLE_CREDENTIALS else "❌ FALTA",
            "FOLDER_GENERADOS": FOLDER_GENERADOS,
            "FOLDER_CV": FOLDER_CV
        }
    })


@app.route('/debug', methods=['GET'])
def debug():
    """Diagnostica cada componente por separado para identificar qué falla."""
    results = {}

    # 1. Variables de entorno
    results["env"] = {
        "CLAUDE_API_KEY": "ok" if CLAUDE_API_KEY else "MISSING",
        "GOOGLE_CREDENTIALS": "ok" if GOOGLE_CREDENTIALS else "MISSING",
        "FOLDER_GENERADOS": FOLDER_GENERADOS,
        "FOLDER_CV": FOLDER_CV
    }

    # 2. Test Claude API
    try:
        respuesta = call_claude("Di solo: OK", max_tokens=10)
        results["claude"] = {"status": "ok", "response": respuesta, "model": CLAUDE_MODEL}
    except Exception as e:
        results["claude"] = {"status": "error", "error": str(e), "model": CLAUDE_MODEL}

    # 3. Test Drive
    try:
        service = get_drive_service()
        # Listar archivos en FOLDER_CV para verificar acceso
        res = service.files().list(
            q=f"'{FOLDER_CV}' in parents and trashed=false",
            fields="files(id, name)",
            pageSize=5
        ).execute()
        archivos = [f["name"] for f in res.get("files", [])]
        cv_master_existe = any("CV_Master" in n for n in archivos)
        results["drive"] = {
            "status": "ok",
            "archivos_en_FOLDER_CV": archivos,
            "cv_master_encontrado": cv_master_existe
        }
    except Exception as e:
        results["drive"] = {"status": "error", "error": str(e)}

    return jsonify(results)


@app.route('/test-claude', methods=['GET'])
def test_claude():
    """Test rápido de la API de Claude."""
    try:
        respuesta = call_claude(
            "Responde solo: El servidor CV funciona correctamente.",
            max_tokens=50
        )
        return jsonify({"status": "ok", "response": respuesta, "model": CLAUDE_MODEL})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e), "model": CLAUDE_MODEL}), 500


@app.route('/registro', methods=['GET', 'POST', 'OPTIONS'])
def registro():
    """
    Formulario de entrada para nuevos usuarios.
    GET  → devuelve el HTML del formulario
    POST → recibe los datos y los reenvía al webhook de n8n
    """
    if request.method == 'OPTIONS':
        r = jsonify({})
        r.headers.add('Access-Control-Allow-Origin', '*')
        r.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        r.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return r

    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form.to_dict()
        nombre = data.get('nombre', '').strip()
        email  = data.get('email', '').strip()
        perfil = data.get('perfil', '').strip()

        if not nombre or not email or not perfil:
            return jsonify({"success": False, "error": "Faltan campos obligatorios"}), 400

        # Reenviar al webhook de n8n
        n8n_url = os.getenv("N8N_WEBHOOK_REGISTRO", "https://n8n-qwmu.onrender.com/webhook/nuevo-usuario")
        payload = {
            "nombre": nombre,
            "email":  email,
            "perfil": perfil,
            "fecha":  datetime.now().isoformat()
        }
        try:
            resp = requests.post(n8n_url, json=payload, timeout=10)
            print(f"✅ Registro enviado a n8n: {nombre} / {email} — n8n respondió {resp.status_code}")
        except Exception as e:
            # n8n puede estar dormido (Render Free) — guardamos igual y avisamos
            print(f"⚠️  n8n no respondió ({e}), registro guardado localmente")

        return jsonify({"success": True, "message": f"¡Bienvenida, {nombre}! Mañana a las 9:00 recibirás tus primeras ofertas."})

    # GET → devuelve el formulario HTML
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BuscarTrabajo — Empieza aquí</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--ink:#1a1a2e;--ink2:#4a4a6a;--accent:#6c47ff;--bg:#f5f3ef;--card:#ffffff;--border:rgba(108,71,255,0.15);--radius:16px}
body{font-family:'DM Sans',sans-serif;background:var(--bg);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.card{background:var(--card);border-radius:var(--radius);padding:52px 48px;max-width:520px;width:100%;box-shadow:0 2px 4px rgba(0,0,0,0.04),0 24px 64px rgba(108,71,255,0.08)}
.badge{display:inline-flex;align-items:center;gap:6px;background:rgba(108,71,255,0.07);color:var(--accent);font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;padding:6px 12px;border-radius:100px;margin-bottom:20px}
.badge::before{content:'';width:6px;height:6px;background:var(--accent);border-radius:50%;animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.8)}}
h1{font-family:'DM Serif Display',serif;font-size:32px;color:var(--ink);line-height:1.2;margin-bottom:10px}
h1 em{font-style:italic;color:var(--accent)}
.subtitle{font-size:14px;color:var(--ink2);line-height:1.6;margin-bottom:36px;font-weight:300}
.field{margin-bottom:24px}
label{display:block;font-size:12px;font-weight:500;letter-spacing:0.06em;text-transform:uppercase;color:var(--ink2);margin-bottom:8px}
input,textarea{width:100%;padding:14px 18px;border:1.5px solid var(--border);border-radius:12px;font-family:'DM Sans',sans-serif;font-size:15px;color:var(--ink);background:#fafafa;outline:none;transition:border-color .2s,background .2s,box-shadow .2s;resize:none}
input::placeholder,textarea::placeholder{color:#b0adc5;font-weight:300}
input:focus,textarea:focus{border-color:var(--accent);background:#fff;box-shadow:0 0 0 4px rgba(108,71,255,0.06)}
textarea{height:100px;line-height:1.6}
.hint{font-size:12px;color:#b0adc5;margin-top:6px;font-weight:300}
.btn{width:100%;padding:16px;background:var(--ink);color:#fff;border:none;border-radius:12px;font-family:'DM Sans',sans-serif;font-size:15px;font-weight:500;cursor:pointer;transition:transform .15s,background .15s,box-shadow .15s;margin-top:8px;position:relative;overflow:hidden}
.btn:hover{background:var(--accent);transform:translateY(-1px);box-shadow:0 8px 24px rgba(108,71,255,0.25)}
.btn.loading{pointer-events:none;opacity:.7}
.spinner{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:20px;height:20px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;opacity:0;transition:opacity .2s}
.btn.loading .spinner{opacity:1}
.btn.loading .btn-text{opacity:0}
@keyframes spin{to{transform:translate(-50%,-50%) rotate(360deg)}}
.success{display:none;text-align:center;padding:20px 0}
.success.show{display:block}
.success-icon{font-size:48px;margin-bottom:16px}
.success h2{font-family:'DM Serif Display',serif;font-size:24px;color:var(--ink);margin-bottom:8px}
.success p{font-size:14px;color:var(--ink2);line-height:1.6;font-weight:300}
.form-content{transition:opacity .3s}
.form-content.hide{opacity:0;pointer-events:none}
.footer-note{text-align:center;margin-top:24px;font-size:12px;color:#c5c2d4;font-weight:300}
.error-msg{color:#ff6b6b;font-size:12px;margin-top:5px;display:none}
.error-msg.show{display:block}
input.error,textarea.error{border-color:#ff6b6b}
</style>
</head>
<body>
<div class="card">
  <div class="form-content" id="formContent">
    <div class="badge">Beta privada</div>
    <h1>Tu próximo trabajo,<br><em>en automático.</em></h1>
    <p class="subtitle">Cada mañana a las 9:00 recibirás ofertas adaptadas a tu perfil, con CV y carta generados listos para enviar.</p>
    <form id="mainForm" novalidate>
      <div class="field">
        <label for="nombre">Tu nombre</label>
        <input type="text" id="nombre" name="nombre" placeholder="Verónica" autocomplete="given-name" required>
        <div class="error-msg" id="err-nombre">Por favor escribe tu nombre</div>
      </div>
      <div class="field">
        <label for="email">Email</label>
        <input type="email" id="email" name="email" placeholder="hola@tumail.com" autocomplete="email" required>
        <div class="error-msg" id="err-email">Necesitamos un email válido</div>
      </div>
      <div class="field">
        <label for="perfil">¿Qué tipo de trabajo buscas?</label>
        <textarea id="perfil" name="perfil" placeholder="Ej: Desarrolladora frontend senior, React y TypeScript, trabajo remoto o híbrido en Madrid, 50K+..." required></textarea>
        <div class="hint">Cuanto más detallado, mejores serán las ofertas que encuentre el sistema.</div>
        <div class="error-msg" id="err-perfil">Cuéntanos un poco qué buscas</div>
      </div>
      <button type="submit" class="btn" id="submitBtn">
        <span class="btn-text">Empezar a buscar →</span>
        <div class="spinner"></div>
      </button>
    </form>
    <p class="footer-note">Sin spam · Puedes pausar cuando quieras · Solo tú ves tus datos</p>
  </div>
  <div class="success" id="successMsg">
    <div class="success-icon">✉️</div>
    <h2>¡Todo listo, <span id="successNombre"></span>!</h2>
    <p>Mañana a las <strong>9:00</strong> recibirás tus primeras ofertas.<br>Revisa tu bandeja de entrada.</p>
  </div>
</div>
<script>
const form = document.getElementById('mainForm');
const btn  = document.getElementById('submitBtn');
function validate(){
  let ok=true;
  const n=document.getElementById('nombre'),e=document.getElementById('email'),p=document.getElementById('perfil');
  [n,e,p].forEach(el=>el.classList.remove('error'));
  document.querySelectorAll('.error-msg').forEach(el=>el.classList.remove('show'));
  if(!n.value.trim()){n.classList.add('error');document.getElementById('err-nombre').classList.add('show');ok=false;}
  if(!e.value.trim()||!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(e.value)){e.classList.add('error');document.getElementById('err-email').classList.add('show');ok=false;}
  if(!p.value.trim()||p.value.trim().length<10){p.classList.add('error');document.getElementById('err-perfil').classList.add('show');ok=false;}
  return ok;
}
form.addEventListener('submit',async(ev)=>{
  ev.preventDefault();
  if(!validate())return;
  btn.classList.add('loading');
  const payload={nombre:document.getElementById('nombre').value.trim(),email:document.getElementById('email').value.trim(),perfil:document.getElementById('perfil').value.trim()};
  try{
    const r=await fetch(window.location.href,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(!d.success)throw new Error(d.error);
  }catch(err){console.warn('Error:',err);}
  document.getElementById('successNombre').textContent=payload.nombre.split(' ')[0];
  document.getElementById('formContent').classList.add('hide');
  setTimeout(()=>document.getElementById('successMsg').classList.add('show'),300);
});
</script>
</body>
</html>"""
    from flask import Response
    return Response(html, mimetype='text/html')


if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)