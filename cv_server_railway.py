#!/usr/bin/env python3
"""
CV Server v2 — MULTI-USER (OAuth mode)

Usa Google OAuth (CLIENT_ID + CLIENT_SECRET + REFRESH_TOKEN) en lugar de service account.
"""

from flask import Flask, request, jsonify, render_template_string
import json, os, re, requests, base64, io
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

app = Flask(__name__)

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
FOLDER_GENERADOS = os.getenv("FOLDER_GENERADOS", "1tHuVOIz3ratjRp8AmHsF0kGVpmy9DocY")
FOLDER_CV_MASTERS = os.getenv("FOLDER_CV_MASTERS") or os.getenv("FOLDER_CV", "1duJA_G3lLbOqiUYoSJcsXAvbtJUdcmzR")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "ntn_G464872773099dpLY7OzD7I4ZeZee38rKHsoVlmCV2z7A0")
NOTION_DB_USUARIOS = os.getenv("NOTION_DB_USUARIOS", "34811515f4b280f19a42f8da5e91a8fe")
N8N_WEBHOOK_NUEVO = os.getenv("N8N_WEBHOOK_NUEVO", "https://n8n-qwmu.onrender.com/webhook/nuevo-usuario")
N8N_WEBHOOK_BUSCAR = os.getenv("N8N_WEBHOOK_BUSCAR", "https://n8n-qwmu.onrender.com/webhook/buscar-ahora")

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive"]

BLUE = RGBColor(0x1F, 0x5C, 0x8B)
DARK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x66, 0x66, 0x66)


# ─────────────────────────────────────────────
# NOTION
# ─────────────────────────────────────────────
def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }


def crear_usuario_en_notion(data):
    """Crea el usuario directamente en Notion DB Usuarios. Devuelve el page_id."""
    stack = data.get("stack", [])
    if isinstance(stack, str):
        stack = [stack] if stack else []
    modalidad = data.get("modalidad", [])
    if isinstance(modalidad, str):
        modalidad = [modalidad] if modalidad else []

    salario = data.get("salario_min") or data.get("salario") or 0
    try:
        salario = int(salario)
    except (ValueError, TypeError):
        salario = 0

    linkedin = data.get("linkedin") or None
    cv_url   = data.get("cv_master_url") or None

    body = {
        "parent": {"database_id": NOTION_DB_USUARIOS},
        "properties": {
            "Name":            {"title":      [{"text": {"content": data.get("nombre", "")}}]},
            "Email":           {"email":      data.get("email", "").strip().lower()},
            "Perfil":          {"rich_text":  [{"text": {"content": data.get("perfil", "")}}]},
            "Activo":          {"checkbox":   True},
            "Rol objetivo":    {"rich_text":  [{"text": {"content": data.get("rol_objetivo", "") or data.get("rol", "")}}]},
            "Stack":           {"multi_select": [{"name": s} for s in stack]},
            "Salario min":     {"number":     salario if salario else None},
            "Modalidad":       {"multi_select": [{"name": m} for m in modalidad]},
            "Ciudad":          {"rich_text":  [{"text": {"content": data.get("ciudad", "")}}]},
        }
    }
    if linkedin:
        body["properties"]["LinkedIn"] = {"url": linkedin}
    if cv_url:
        body["properties"]["CV Master URL"] = {"url": cv_url}

    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=notion_headers(),
        json=body,
        timeout=30
    )
    if r.status_code not in (200, 201):
        raise Exception(f"Notion crear usuario error {r.status_code}: {r.text[:300]}")
    return r.json().get("id", "")


def buscar_usuario_por_email(email):
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}/query",
        headers=notion_headers(),
        json={"filter": {"property": "Email", "email": {"equals": email}}, "page_size": 1},
        timeout=30
    )
    if r.status_code != 200:
        raise Exception(f"Notion query error {r.status_code}: {r.text[:200]}")
    results = r.json().get("results", [])
    if not results:
        return None
    return normalizar_perfil(results[0])


def normalizar_perfil(notion_page):
    p = notion_page.get("properties", {})
    return {
        "user_id": notion_page.get("id", ""),
        "nombre":  (p.get("Name", {}).get("title") or [{}])[0].get("plain_text", ""),
        "email":   p.get("Email", {}).get("email", "") or "",
        "perfil":  (p.get("Perfil", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "activo":  p.get("Activo", {}).get("checkbox", False),
        "rol":     (p.get("Rol objetivo", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "stack":   [s["name"] for s in p.get("Stack", {}).get("multi_select", [])],
        "salario_min": p.get("Salario min", {}).get("number", 0) or 0,
        "modalidad":[m["name"] for m in p.get("Modalidad", {}).get("multi_select", [])],
        "ciudad":  (p.get("Ciudad", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "linkedin":p.get("LinkedIn", {}).get("url", "") or "",
        "cv_master_url": p.get("CV Master URL", {}).get("url", "") or "",
        "telefono":(p.get("Telefono", {}).get("phone_number", "") or "")
    }


# ─────────────────────────────────────────────
# GOOGLE DRIVE (OAuth)
# ─────────────────────────────────────────────
def get_drive_service():
    """Autentica con Google Drive usando OAuth (CLIENT_ID + CLIENT_SECRET + REFRESH_TOKEN)."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REFRESH_TOKEN:
        raise Exception(
            "Faltan variables Google OAuth. "
            "Configura GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET y GOOGLE_REFRESH_TOKEN en Render."
        )

    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=GOOGLE_SCOPES
    )

    try:
        creds.refresh(Request())
    except Exception as e:
        raise Exception(f"No se pudo renovar el access_token Google OAuth: {e}")

    return build("drive", "v3", credentials=creds)


def leer_cv_master_por_email(service, email):
    usuario = buscar_usuario_por_email(email)
    if not usuario:
        raise Exception(f"Usuario {email} no encontrado en Notion DB Usuarios")

    if usuario.get("cv_master_url"):
        url = usuario["cv_master_url"]
        m = re.search(r'/d/([a-zA-Z0-9_-]+)', url) or re.search(r'id=([a-zA-Z0-9_-]+)', url)
        if m:
            file_id = m.group(1)
            return _descargar_txt(service, file_id), usuario

    email_slug = email.replace("@", "_at_").replace(".", "_")
    nombres_posibles = [
        f"CV_Master_{email_slug}.txt",
        f"{email_slug}.txt",
        f"CV_Master_{usuario['nombre'].replace(' ', '_')}.txt"
    ]
    for nombre in nombres_posibles:
        results = service.files().list(
            q=f"name='{nombre}' and '{FOLDER_CV_MASTERS}' in parents and trashed=false",
            fields="files(id, name)"
        ).execute()
        files = results.get("files", [])
        if files:
            return _descargar_txt(service, files[0]["id"]), usuario

    # Fallback legacy
    results = service.files().list(
        q=f"name='CV_Master_Veronica.txt' and '{FOLDER_CV_MASTERS}' in parents and trashed=false",
        fields="files(id)"
    ).execute()
    files = results.get("files", [])
    if files and email == "hello.cookyourweb@gmail.com":
        return _descargar_txt(service, files[0]["id"]), usuario

    raise Exception(
        f"No se encontró CV Master para {email}. "
        f"Sube un archivo con nombre CV_Master_{email_slug}.txt a la carpeta Drive {FOLDER_CV_MASTERS} "
        f"o rellena 'CV Master URL' en Notion DB Usuarios."
    )


def _descargar_txt(service, file_id):
    req = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read().decode("utf-8")


# ─────────────────────────────────────────────
# LLM — Gemini
# ─────────────────────────────────────────────
def call_llm(prompt, max_tokens=6000):
    """Llama a Gemini API. Retorna el texto de la respuesta."""
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY no configurada")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    r = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7
            }
        },
        timeout=90
    )
    if r.status_code != 200:
        raise Exception(f"Gemini API error {r.status_code}: {r.text[:500]}")

    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise Exception(f"Respuesta Gemini inesperada: {json.dumps(data)[:300]}")


def generar_cv_adaptado(cv_master, empresa, puesto, descripcion, usuario):
    nombre = usuario["nombre"]
    perfil_libre = usuario.get("perfil", "")
    rol_objetivo = usuario.get("rol", "")

    prompt = f"""Act as a senior tech recruiter who screens 200+ resumes daily.
You are adapting {nombre}'s resume for a specific job offer.

STEP 1 — INTERNAL ANALYSIS (do this first silently, do NOT output it):
- Which skills in the master CV are most relevant to this offer?
- Which terminology from the offer should appear in the adapted CV?
- Which achievements best demonstrate fit for this specific role?
- Are there gaps? (If a required skill is missing, do NOT invent — just don't include that gap)
- Match score 1-10 — is this a real fit?

STEP 2 — OUTPUT: Generate ONLY the adapted CV content following these rules.

CANDIDATE CONTEXT:
- Name: {nombre}
- Target role: {rol_objetivo or 'Not specified'}
- Candidate's own words: {perfil_libre or 'Not specified'}

MASTER CV:
{cv_master}

OFFER:
- Company: {empresa}
- Position: {puesto}
- Description: {descripcion}

NON-NEGOTIABLE RULES:
1. QUANTIFY EVERY BULLET
2. CUT GENERIC LANGUAGE
3. LEAD WITH PROOF
4. MATCH OFFER KEYWORDS HONESTLY
5. ORDER SKILLS BY RELEVANCE
6. MAXIMUM 2 PAGES

OUTPUT FORMAT (plain text, no markdown):

PERFIL PROFESIONAL
[2-3 líneas]

EXPERIENCIA PROFESIONAL
Empresa — Ciudad
Puesto
Fecha inicio – Fecha fin
- Logro 1 con métrica
- Logro 2 con métrica

HABILIDADES TÉCNICAS
[Skills ordenadas por relevancia]

FORMACIÓN
Título — Institución (Año)

IDIOMAS
Idioma: Nivel

RULES:
- NO markdown (**, #, ```, -)
- NO cabecera (nombre/email/teléfono) — se añade programáticamente
- NO texto introductorio ni conclusiones
- Usa guiones normales (-) para bullets
- Separa secciones con línea en blanco"""

    response = call_llm(prompt)

    lines = response.strip().split('\n')
    cleaned = []
    in_code = False
    for line in lines:
        s = line.strip()
        if s.startswith('```'):
            in_code = not in_code
            continue
        if in_code:
            continue
        if s.lower().startswith(('aquí', 'here', 'este', 'this', 'espero', 'i hope')):
            continue
        clean = s.replace('**', '').replace('`', '').replace('#', '').strip()
        if clean:
            cleaned.append(clean)
    return '\n'.join(cleaned)


# ─────────────────────────────────────────────
# DOCX
# ─────────────────────────────────────────────
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


def generar_docx(cv_texto, output_path, usuario):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(10)

    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    nombre = usuario.get("nombre", "Candidato")
    rol = usuario.get("rol", "")
    ciudad = usuario.get("ciudad", "")
    telefono = usuario.get("telefono", "")
    email = usuario.get("email", "")
    linkedin = usuario.get("linkedin", "")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(nombre.upper())
    r.bold = True
    r.font.size = Pt(18)
    r.font.color.rgb = DARK

    if rol:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(rol)
        r.font.size = Pt(11)
        r.font.color.rgb = BLUE

    contact_parts = [c for c in [ciudad, telefono, email, linkedin.replace("https://", "").replace("http://", "")] if c]
    if contact_parts:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(" · ".join(contact_parts))
        r.font.size = Pt(8.5)
        r.font.color.rgb = GREY

    p = doc.add_paragraph()
    add_border_bottom(p)

    SECTIONS = ['PERFIL PROFESIONAL', 'EXPERIENCIA PROFESIONAL', 'EXPERIENCIA',
                'HABILIDADES TÉCNICAS', 'HABILIDADES', 'FORMACIÓN', 'IDIOMAS',
                'COMPETENCIAS', 'PROYECTOS', 'CERTIFICACIONES', 'EDUCACIÓN']

    for line in cv_texto.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        if nombre.upper() in line.upper() or line.startswith('# '):
            continue

        clean = re.sub(r'^#{1,3}\s*', '', line).strip().replace('```', '')
        clean_upper = re.sub(r'\*\*', '', clean).upper().strip()

        if any(kw in clean_upper for kw in SECTIONS) and len(clean) < 40:
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

        if re.search(r'(20\d{2}|19\d{2})', line) and len(line) < 60:
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


# ─────────────────────────────────────────────
# DRIVE UPLOAD
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# ORQUESTADOR
# ─────────────────────────────────────────────
def generar_y_subir_cv(email, empresa, puesto, descripcion):
    steps = []
    try:
        service = get_drive_service()
        steps.append("drive_connect")

        cv_master, usuario = leer_cv_master_por_email(service, email)
        steps.append("cv_master_read")

        if not usuario.get("activo", True):
            raise Exception(f"Usuario {email} está inactivo en Notion")

        cv_adaptado = generar_cv_adaptado(cv_master, empresa, puesto, descripcion, usuario)
        steps.append("llm_generate")

        fecha = datetime.now().strftime("%Y-%m-%d")
        email_slug = re.sub(r'[^a-zA-Z0-9]', '-', email)[:30]
        empresa_slug = re.sub(r'[^a-zA-Z0-9]', '-', empresa)[:30]
        puesto_slug = re.sub(r'[^a-zA-Z0-9]', '-', puesto)[:30]

        folder_user = crear_carpeta_drive(service, email_slug, FOLDER_GENERADOS)
        folder_oferta = crear_carpeta_drive(service, f"{fecha}_{empresa_slug}_{puesto_slug}", folder_user)

        nombre_archivo = f"CV_{usuario['nombre'].replace(' ', '_')}_{empresa_slug}.docx"
        temp_path = f"/tmp/{nombre_archivo}"
        generar_docx(cv_adaptado, temp_path, usuario)
        steps.append("docx_generated")

        link = subir_a_drive(service, temp_path, nombre_archivo, folder_oferta)
        steps.append("drive_upload")

        if os.path.exists(temp_path):
            os.remove(temp_path)

        return {
            "success": True,
            "link": link,
            "archivo": nombre_archivo,
            "usuario": usuario["nombre"],
            "email": email,
            "carpeta_usuario": email_slug,
            "modelo_usado": GEMINI_MODEL
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "steps_completed": steps,
            "traceback": traceback.format_exc()[-1000:]
        }


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────
@app.route('/generar-cv', methods=['POST', 'OPTIONS'])
def endpoint_generar_cv():
    if request.method == 'OPTIONS':
        resp = jsonify({})
        resp.headers.add('Access-Control-Allow-Origin', '*')
        resp.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        resp.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return resp

    data = request.get_json() or {}
    email = data.get("email")
    if not email:
        return jsonify({"success": False, "error": "Parámetro 'email' obligatorio"}), 400

    resultado = generar_y_subir_cv(
        email=email,
        empresa=data.get("empresa", "Empresa"),
        puesto=data.get("puesto", "Puesto"),
        descripcion=data.get("descripcion", "")
    )
    resp = jsonify(resultado)
    resp.headers.add('Access-Control-Allow-Origin', '*')
    return resp


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "version": "v2.2.1-gemini-2.0",
        "llm_provider": "gemini",
        "model": GEMINI_MODEL,
        "auth_mode": "oauth",
        "env_vars": {
            "GEMINI_API_KEY":       "✅" if GEMINI_API_KEY else "❌ FALTA",
            "GOOGLE_CLIENT_ID":     "✅" if GOOGLE_CLIENT_ID else "❌ FALTA",
            "GOOGLE_CLIENT_SECRET": "✅" if GOOGLE_CLIENT_SECRET else "❌ FALTA",
            "GOOGLE_REFRESH_TOKEN": "✅" if GOOGLE_REFRESH_TOKEN else "❌ FALTA",
            "NOTION_TOKEN":         "✅" if NOTION_TOKEN else "❌ FALTA",
            "NOTION_DB_USUARIOS":   NOTION_DB_USUARIOS,
            "FOLDER_GENERADOS":     FOLDER_GENERADOS,
            "FOLDER_CV_MASTERS":    FOLDER_CV_MASTERS,
            "N8N_WEBHOOK_NUEVO":    "✅" if N8N_WEBHOOK_NUEVO else "❌ FALTA",
            "N8N_WEBHOOK_BUSCAR":   "✅" if N8N_WEBHOOK_BUSCAR else "❌ FALTA"
        }
    })


@app.route('/debug', methods=['GET'])
def debug():
    results = {"version": "v2.2.1-gemini-2.0", "llm_provider": "gemini"}

    try:
        r = call_llm("Say only: OK", max_tokens=10)
        results["gemini"] = {"status": "ok", "response": r}
    except Exception as e:
        results["gemini"] = {"status": "error", "error": str(e)}

    try:
        service = get_drive_service()
        res = service.files().list(
            q=f"'{FOLDER_CV_MASTERS}' in parents and trashed=false",
            fields="files(id, name)", pageSize=20
        ).execute()
        results["drive"] = {
            "status": "ok",
            "archivos_en_FOLDER_CV_MASTERS": [f["name"] for f in res.get("files", [])]
        }
    except Exception as e:
        results["drive"] = {"status": "error", "error": str(e)}

    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}/query",
            headers=notion_headers(), json={"page_size": 5}, timeout=20
        )
        if r.status_code == 200:
            users = [normalizar_perfil(p) for p in r.json().get("results", [])]
            results["notion_usuarios"] = {
                "status": "ok",
                "total_visibles": len(users),
                "emails": [u["email"] for u in users]
            }
        else:
            results["notion_usuarios"] = {"status": "error", "code": r.status_code, "body": r.text[:200]}
    except Exception as e:
        results["notion_usuarios"] = {"status": "error", "error": str(e)}

    return jsonify(results)


@app.route('/test-llm', methods=['GET'])
@app.route('/test-claude', methods=['GET'])  # alias retrocompatible
def test_llm():
    try:
        r = call_llm("Responde solo: El servidor CV v2 funciona correctamente.", max_tokens=50)
        return jsonify({
            "status": "ok",
            "provider": "gemini",
            "model": GEMINI_MODEL,
            "response": r
        })
    except Exception as e:
        return jsonify({"status": "error", "provider": "gemini", "error": str(e)}), 500


@app.route('/usuarios', methods=['GET'])
def listar_usuarios():
    """Lista todos los usuarios registrados en Notion DB Usuarios."""
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}/query",
            headers=notion_headers(),
            json={"page_size": 100},
            timeout=30
        )
        if r.status_code != 200:
            return jsonify({"error": f"Notion error {r.status_code}", "details": r.text[:300]}), 500

        results = r.json().get("results", [])
        usuarios = []
        for p in results:
            props = p.get("properties", {})
            usuarios.append({
                "id": p.get("id", ""),
                "nombre": (props.get("Name", {}).get("title") or [{}])[0].get("plain_text", ""),
                "email": props.get("Email", {}).get("email", ""),
                "activo": props.get("Activo", {}).get("checkbox", False),
                "rol": (props.get("Rol objetivo", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
                "ciudad": (props.get("Ciudad", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
                "created_time": p.get("created_time", "")
            })

        # Ordenar por fecha de creación (más reciente primero)
        usuarios.sort(key=lambda u: u.get("created_time", ""), reverse=True)

        return jsonify({
            "total": len(usuarios),
            "usuarios": usuarios
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# FORMULARIO DE REGISTRO
# ─────────────────────────────────────────────
HTML_REGISTRO = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BuscarTrabajo — Registro</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f9fafb; color: #1a1a1a; padding: 40px 20px; min-height: 100vh; }
  .container { max-width: 560px; margin: 0 auto; background: white; padding: 48px 40px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); }
  h1 { font-size: 28px; margin-bottom: 8px; color: #1F5C8B; }
  .subtitle { color: #666; margin-bottom: 32px; font-size: 15px; }
  label { display: block; margin-top: 20px; font-weight: 600; font-size: 14px; color: #333; }
  input, textarea, select { width: 100%; padding: 12px 14px; margin-top: 6px; border: 1px solid #e0e0e0; border-radius: 8px; font-size: 15px; font-family: inherit; background: #fafafa; transition: border 0.2s; }
  input:focus, textarea:focus, select:focus { outline: none; border-color: #1F5C8B; background: white; }
  textarea { min-height: 100px; resize: vertical; }
  .btn { width: 100%; padding: 14px; background: #1F5C8B; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 24px; transition: background 0.2s; }
  .btn:hover { background: #164669; }
  .btn:disabled { background: #999; cursor: not-allowed; }
  .btn-secondary { background: #22C55E; }
  .btn-secondary:hover { background: #16A34A; }
  .btn-outline { background: white; color: #1F5C8B; border: 2px solid #1F5C8B; }
  .btn-outline:hover { background: #f0f7ff; }
  .screen { display: none; }
  .screen.active { display: block; }
  .check-group { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
  .check-item { padding: 8px 14px; border: 1px solid #ddd; border-radius: 20px; cursor: pointer; font-size: 13px; user-select: none; transition: all 0.2s; }
  .check-item.active { background: #1F5C8B; color: white; border-color: #1F5C8B; }
  .hint { font-size: 12px; color: #888; margin-top: 4px; }
  .button-row { display: flex; gap: 12px; margin-top: 24px; }
  .button-row .btn { margin-top: 0; }
</style>
</head>
<body>
<div class="container">

  <!-- Enlace para ver usuarios registrados -->
  <p style="text-align:center; margin-bottom:20px;">
    <a href="/usuarios" target="_blank" style="color:#1F5C8B;font-size:14px;text-decoration:none;">📋 Ver usuarios registrados en Notion</a>
  </p>

  <div id="screen1" class="screen active">
    <h1>🎯 BuscarTrabajo</h1>
    <p class="subtitle">Te buscamos trabajo mientras duermes. Cuéntanos qué buscas.</p>

    <form id="form1">
      <label>Nombre completo *</label>
      <input type="text" name="nombre" required>

      <label>Email *</label>
      <input type="email" name="email" required>
      <p class="hint">Usaremos este email para enviarte las ofertas cada mañana.</p>

      <label>Rol objetivo</label>
      <input type="text" name="rol_objetivo" placeholder="Ej: Senior Frontend Developer / Tech Lead">

      <label>Ciudad</label>
      <input type="text" name="ciudad" placeholder="Madrid">

      <label>Modalidad preferida</label>
      <div class="check-group" data-name="modalidad">
        <div class="check-item" data-value="Remoto">🏠 Remoto</div>
        <div class="check-item" data-value="Híbrido Madrid">🚇 Híbrido Madrid</div>
        <div class="check-item" data-value="Híbrido BCN">🚇 Híbrido BCN</div>
        <div class="check-item" data-value="Presencial">🏢 Presencial</div>
      </div>

      <label>Stack técnico</label>
      <div class="check-group" data-name="stack">
        <div class="check-item" data-value="React">React</div>
        <div class="check-item" data-value="TypeScript">TypeScript</div>
        <div class="check-item" data-value="Vue.js">Vue.js</div>
        <div class="check-item" data-value="Node.js">Node.js</div>
        <div class="check-item" data-value="Python">Python</div>
        <div class="check-item" data-value="Java">Java</div>
        <div class="check-item" data-value="Go">Go</div>
        <div class="check-item" data-value="AI/ML">AI/ML</div>
        <div class="check-item" data-value="DevOps">DevOps</div>
        <div class="check-item" data-value="AWS">AWS</div>
      </div>

      <label>Salario mínimo anual (€)</label>
      <input type="number" name="salario_min" placeholder="60000" min="0" step="1000">

      <label>LinkedIn</label>
      <input type="url" name="linkedin" placeholder="https://linkedin.com/in/...">

      <label>CV Master (link Google Drive, opcional)</label>
      <input type="url" name="cv_master_url" placeholder="https://drive.google.com/file/d/...">
      <p class="hint">Deja el enlace de tu CV base en Drive con permiso de lectura.</p>

      <label>Cuéntanos qué buscas (libre) *</label>
      <textarea name="perfil" required placeholder="Busco un rol de Tech Lead Frontend en empresa de producto..."></textarea>

      <button type="submit" class="btn" id="btn1">🚀 Empezar</button>
    </form>
  </div>

  <div id="screen2" class="screen">
    <h1 id="saludo">¡Hola de nuevo!</h1>
    <p class="subtitle">¿Cuándo quieres que busquemos ofertas?</p>
    <div class="button-row">
      <button class="btn btn-secondary" onclick="accionExistente('ahora')">⚡ Buscar ahora</button>
      <button class="btn btn-outline" onclick="accionExistente('manana')">🌅 Mañana a las 9</button>
    </div>
  </div>

  <div id="screen3" class="screen">
    <h1>✅ ¡Listo!</h1>
    <p class="subtitle" id="confirmacion">Todo en orden.</p>
  </div>

</div>

<script>
  document.querySelectorAll('.check-group').forEach(group => {
    group.querySelectorAll('.check-item').forEach(item => {
      item.addEventListener('click', () => item.classList.toggle('active'));
    });
  });

  function getChecked(name) {
    return Array.from(document.querySelectorAll(`[data-name="${name}"] .check-item.active`))
      .map(el => el.dataset.value);
  }

  function showScreen(n) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen' + n).classList.add('active');
  }

  let currentEmail = '';
  let currentNombre = '';

  document.getElementById('form1').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('btn1');
    btn.disabled = true;
    btn.textContent = 'Procesando...';

    const fd = new FormData(e.target);
    const data = {
      nombre:        fd.get('nombre'),
      email:         fd.get('email'),
      perfil:        fd.get('perfil'),
      rol_objetivo:  fd.get('rol_objetivo'),
      ciudad:        fd.get('ciudad'),
      linkedin:      fd.get('linkedin'),
      cv_master_url: fd.get('cv_master_url'),
      salario_min:   fd.get('salario_min'),
      modalidad:     getChecked('modalidad'),
      stack:         getChecked('stack')
    };
    currentEmail  = data.email;
    currentNombre = data.nombre;

    try {
      const r = await fetch('/registro', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
      const j = await r.json();

      if (j.estado === 'existente') {
        document.getElementById('saludo').textContent = `¡Hola de nuevo, ${j.nombre}!`;
        showScreen(2);
      } else if (j.estado === 'creado') {
        document.getElementById('confirmacion').textContent =
          'Te has registrado correctamente. Mañana a las 9:00 recibirás tus primeras 5 ofertas personalizadas.';
        showScreen(3);
      } else {
        throw new Error(j.error || 'Error desconocido');
      }
    } catch (err) {
      btn.disabled = false;
      btn.textContent = '🚀 Empezar';
      alert('Error: ' + err.message);
    }
  });

  async function accionExistente(accion) {
    try {
      const r = await fetch('/registro', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ email: currentEmail, nombre: currentNombre, accion })
      });
      const j = await r.json();

      if (accion === 'ahora') {
        document.getElementById('confirmacion').textContent =
          'Buscando ahora mismo. Recibirás las ofertas en unos minutos.';
      } else {
        document.getElementById('confirmacion').textContent =
          'De acuerdo. Mañana a las 9:00 recibirás tus ofertas personalizadas.';
      }
      showScreen(3);
    } catch (err) {
      alert('Error: ' + err.message);
    }
  }
</script>
</body>
</html>"""


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'GET':
        return render_template_string(HTML_REGISTRO)

    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    accion = data.get("accion")

    if not email:
        return jsonify({"error": "Email requerido"}), 400

    if accion in ("ahora", "manana"):
        if accion == "ahora":
            try:
                requests.post(
                    N8N_WEBHOOK_BUSCAR,
                    json={"email": email, "nombre": data.get("nombre", "")},
                    timeout=5
                )
            except Exception as e:
                print(f"⚠️ Webhook buscar-ahora falló: {e}")
        return jsonify({"estado": "ok", "accion": accion})

    try:
        usuario = buscar_usuario_por_email(email)
    except Exception as e:
        return jsonify({"error": f"Error consultando Notion: {e}"}), 500

    if usuario:
        return jsonify({
            "estado": "existente",
            "nombre": usuario["nombre"],
            "email": email
        })

    # ── Guardar directamente en Notion (sin depender de n8n) ──
    try:
        crear_usuario_en_notion(data)
    except Exception as e:
        return jsonify({"error": f"Error guardando en Notion: {e}"}), 500

    # ── Disparar búsqueda en n8n en background (best-effort, no bloquea) ──
    try:
        payload = {k: v for k, v in data.items() if k != "accion"}
        requests.post(N8N_WEBHOOK_NUEVO, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Webhook n8n nuevo-usuario falló (no crítico): {e}")

    return jsonify({"estado": "creado", "email": email, "nombre": data.get("nombre", "")})


if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)