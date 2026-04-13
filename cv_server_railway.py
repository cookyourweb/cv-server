#!/usr/bin/env python3
"""
Servidor HTTP para generar CVs adaptados y subirlos a Drive.
Versión para Railway - usa variables de entorno.
"""

from flask import Flask, request, jsonify
import json, os, re, requests, base64, io
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

app = Flask(__name__)

FOLDER_GENERADOS = os.getenv("FOLDER_GENERADOS", "1tHuVOIz3ratjRp8AmHsF0kGVpmy9DocY")
FOLDER_CV        = os.getenv("FOLDER_CV", "1duJA_G3lLbOqiUYoSJcsXAvbtJUdcmzR")
CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
MIME_DOCX        = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GOOGLE_SCOPES    = ["https://www.googleapis.com/auth/drive"]


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
    prompt = f"""Eres el asistente de Verónica Serna, Tech Lead UX Engineer.

CV Master completo:
{cv_master}

Genera un CV adaptado para:
- Empresa: {empresa}
- Puesto: {puesto}
- Descripción: {descripcion}

INSTRUCCIONES:
1. Selecciona la experiencia más relevante para esta oferta
2. Reordena skills poniendo primero las más relevantes
3. Adapta el perfil profesional a lo que busca la empresa
4. Tono directo y humano, sin guiones largos
5. Máximo 2 páginas

FORMATO:
# VERÓNICA SERNA
## Tech Lead UX Engineer · AI & Automation Specialist

## PERFIL PROFESIONAL
[3-4 líneas adaptadas]

## EXPERIENCIA
[experiencia relevante con empresa, puesto, fechas y logros]

## HABILIDADES TÉCNICAS
[skills por relevancia para esta oferta]

## FORMACIÓN
[formación relevante]

## IDIOMAS
[idiomas]"""
    return call_claude(prompt)


def generar_docx(cv_texto, output_path):
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    titulo = doc.add_paragraph()
    titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = titulo.add_run("Verónica Serna Pérez")
    run.bold = True; run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)

    subtitulo = doc.add_paragraph()
    subtitulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = subtitulo.add_run("Tech Lead UX Engineer · AI & Automation Specialist")
    run2.font.size = Pt(11)
    run2.font.color.rgb = RGBColor(0x1F, 0x5C, 0x8B)

    contacto = doc.add_paragraph()
    contacto.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run3 = contacto.add_run("Bilbao · verserper@gmail.com · linkedin.com/in/veronica4web")
    run3.font.size = Pt(9)
    run3.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    doc.add_paragraph()

    for linea in cv_texto.strip().split('\n'):
        linea_limpia = linea.strip()
        if not linea_limpia:
            doc.add_paragraph(); continue
        if linea_limpia.startswith('# ') and not linea_limpia.startswith('## '):
            continue
        elif linea_limpia.startswith('## '):
            texto_seccion = linea_limpia.replace('## ', '')
            p = doc.add_paragraph()
            run = p.add_run(texto_seccion.upper())
            run.bold = True; run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0x1F, 0x5C, 0x8B)
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            pPr = p._p.get_or_add_pPr()
            pBdr = OxmlElement('w:pBdr')
            bottom = OxmlElement('w:bottom')
            bottom.set(qn('w:val'), 'single'); bottom.set(qn('w:sz'), '6')
            bottom.set(qn('w:space'), '1'); bottom.set(qn('w:color'), '1F5C8B')
            pBdr.append(bottom); pPr.append(pBdr)
        elif linea_limpia.startswith('- ') or linea_limpia.startswith('• '):
            texto = re.sub(r'\*\*(.*?)\*\*', r'\1', linea_limpia[2:])
            p = doc.add_paragraph(style='List Bullet')
            run = p.add_run(texto); run.font.size = Pt(9.5)
        else:
            linea_limpia = re.sub(r'\*\*(.*?)\*\*', r'\1', linea_limpia)
            linea_limpia = re.sub(r'^#{1,3}\s*', '', linea_limpia)
            if linea_limpia:
                p = doc.add_paragraph(linea_limpia)
                if p.runs: p.runs[0].font.size = Pt(9.5)
    doc.save(output_path)


def crear_carpeta_drive(service, nombre, parent_id):
    res = service.files().list(
        q=f"name='{nombre}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id)"
    ).execute()
    if res["files"]:
        return res["files"][0]["id"]
    meta = {"name": nombre, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


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
        generar_docx(cv_adaptado, temp_path)
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
        response = jsonify({})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
    data = request.get_json()
    resultado = generar_y_subir_cv(
        data.get('empresa', 'Empresa'),
        data.get('puesto', 'Puesto'),
        data.get('descripcion', '')
    )
    response = jsonify(resultado)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
