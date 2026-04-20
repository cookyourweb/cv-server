#!/usr/bin/env python3
"""
CV Server — Genera CVs adaptados profesionales en DOCX y los sube a Drive.
Versión para Render — usa variables de entorno.
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

BLUE = RGBColor(0x1F, 0x5C, 0x8B)
DARK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x66, 0x66, 0x66)


def get_drive_service():
    creds_json = base64.b64decode(GOOGLE_CREDENTIALS).decode("utf-8")
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=GOOGLE_SCOPES)
    return build("drive", "v3", credentials=creds)


def leer_cv_master(service):
    results = service.files().list(
        q=f"name='CV_Master_Veronica.txt' and '{FOLDER_CV}' in parents and trashed=false",
        fields="files(id, name)"
    ).execute()
    files = results.get("files", [])
    if not files:
        raise Exception("No se encontró CV_Master_Veronica.txt en Drive")
    file_id = files[0]["id"]
    req = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return buffer.read().decode("utf-8")


def call_claude(prompt, max_tokens=6000):
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": CLAUDE_API_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        json={"model": "claude-sonnet-4-6", "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    )
    return response.json()["content"][0]["text"]


def generar_cv_adaptado(cv_master, empresa, puesto, descripcion):
    prompt = f"""Eres el asistente de Verónica Serna, Senior Frontend Developer con 15+ años de experiencia.

CV Master completo:
{cv_master}

Genera un CV adaptado para esta oferta:
- Empresa: {empresa}
- Puesto: {puesto}
- Descripción: {descripcion}

INSTRUCCIONES:
1. Selecciona SOLO la experiencia relevante para esta oferta
2. Reordena skills por relevancia para el puesto
3. Adapta el perfil profesional a lo que busca la empresa
4. Tono directo y profesional, sin frases genéricas
5. Máximo 2 páginas
6. NO incluyas cabecera (nombre/contacto) — se añade automáticamente

FORMATO EXACTO (usa estas secciones tal cual):

PERFIL PROFESIONAL
[3-4 líneas adaptadas a esta oferta]

EXPERIENCIA PROFESIONAL

CookYourWebAI — Madrid (Remoto)
Lead Frontend Engineer & AI Integration Specialist
Mayo 2024 – Actualidad
- Logro relevante para esta oferta
- Otro logro

Bitcode Technology (para Ayvens) — Madrid
Tech Lead & Senior Frontend Developer
2017 – Mayo 2024
- Logro relevante
- Otro logro

HABILIDADES TÉCNICAS
React · TypeScript · Next.js · [ordenadas por relevancia]

FORMACIÓN
Máster en IA aplicada — AiFunnelLabs (En curso 2025)
Bootcamp Full Stack Mobile — KeepCoding (2023)

IDIOMAS
Español: Nativo
Inglés: Alto"""
    return call_claude(prompt)


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

        # Skip cabecera generada por Claude
        if 'VERÓNICA SERNA' in line.upper() or line.startswith('# '):
            continue

        # Limpiar markdown
        clean = re.sub(r'^#{1,3}\s*', '', line).strip()
        clean = clean.replace('```', '')
        clean_upper = re.sub(r'\*\*', '', clean).upper().strip()

        # Sección
        is_section = any(kw in clean_upper for kw in SECTIONS)
        if is_section and len(clean) < 40:
            p = doc.add_paragraph()
            r = p.add_run(re.sub(r'\*\*', '', clean).upper())
            r.bold = True; r.font.size = Pt(10); r.font.color.rgb = BLUE
            add_border_bottom(p)
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(6)
            continue

        # Bullet
        if line.startswith(('- ', '• ', '* ')):
            texto = re.sub(r'\*\*(.*?)\*\*', r'\1', line[2:].strip())
            p = doc.add_paragraph()
            r = p.add_run("• " + texto)
            r.font.size = Pt(9.5); r.font.color.rgb = DARK
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.space_after = Pt(2)
            continue

        # Empresa — Ciudad (negrita)
        if ('—' in line or ' – ' in line) and len(line) < 100:
            texto = re.sub(r'\*\*(.*?)\*\*', r'\1', line)
            p = doc.add_paragraph()
            r = p.add_run(texto)
            r.bold = True; r.font.size = Pt(10); r.font.color.rgb = DARK
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(1)
            continue

        # Fechas
        if re.search(r'(20\d{2}|19\d{2})', line) and len(line) < 60 and not line.startswith(('- ', '•')):
            texto = re.sub(r'\*\*(.*?)\*\*', r'\1', line).replace('`', '')
            p = doc.add_paragraph()
            r = p.add_run(texto)
            r.italic = True; r.font.size = Pt(9); r.font.color.rgb = GREY
            p.paragraph_format.space_after = Pt(3)
            continue

        # Texto normal
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
    try:
        print(f"🔗 Conectando a Drive...")
        service = get_drive_service()
        print(f"📖 Leyendo CV Master...")
        cv_master = leer_cv_master(service)
        print(f"🤖 Claude generando CV para {empresa}...")
        cv_adaptado = generar_cv_adaptado(cv_master, empresa, puesto, descripcion)
        fecha = datetime.now().strftime("%Y-%m-%d")
        empresa_slug = re.sub(r'[^a-zA-Z0-9]', '-', empresa)[:30]
        puesto_slug = re.sub(r'[^a-zA-Z0-9]', '-', puesto)[:30]
        nombre_carpeta = f"{fecha}_{empresa_slug}_{puesto_slug}"
        nombre_archivo = f"CV_Veronica_{empresa_slug}.docx"
        print(f"📄 Generando DOCX...")
        temp_path = f"/tmp/{nombre_archivo}"
        generar_docx(cv_adaptado, temp_path, empresa, puesto)
        print(f"☁️  Subiendo a Drive...")
        folder_id = crear_carpeta_drive(service, nombre_carpeta, FOLDER_GENERADOS)
        link = subir_a_drive(service, temp_path, nombre_archivo, folder_id)
        os.remove(temp_path)
        print(f"✅ CV subido: {link}")
        return {"success": True, "link": link, "carpeta": nombre_carpeta, "archivo": nombre_archivo}
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback; traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.route('/generar-cv', methods=['POST', 'OPTIONS'])
def generar_cv():
    if request.method == 'OPTIONS':
        r = jsonify({})
        r.headers.add('Access-Control-Allow-Origin', '*')
        r.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        r.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return r
    data = request.get_json()
    resultado = generar_y_subir_cv(data.get('empresa', 'Empresa'), data.get('puesto', 'Puesto'), data.get('descripcion', ''))
    r = jsonify(resultado)
    r.headers.add('Access-Control-Allow-Origin', '*')
    return r


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)