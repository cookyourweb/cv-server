#!/usr/bin/env python3

from flask import Flask, request, jsonify
import json, os, re, requests, base64, io
from datetime import datetime

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

app = Flask(__name__)

# ── CONFIG ─────────────────────────────────────────────

FOLDER_GENERADOS = os.getenv("FOLDER_GENERADOS")
FOLDER_CV        = os.getenv("FOLDER_CV")
CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

MIME_DOCX     = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive"]

# ── DRIVE ─────────────────────────────────────────────

def get_drive_service():
    creds_json = base64.b64decode(GOOGLE_CREDENTIALS).decode("utf-8")
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=GOOGLE_SCOPES
    )
    return build("drive", "v3", credentials=creds)

def leer_cv_master(service):
    res = service.files().list(
        q=f"name='CV_Master_Veronica.txt' and '{FOLDER_CV}' in parents and trashed=false",
        fields="files(id)"
    ).execute()

    if not res["files"]:
        raise Exception("No se encontró CV_Master")

    file_id = res["files"][0]["id"]

    req = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, req)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)
    return buffer.read().decode("utf-8")

def crear_carpeta_drive(service, nombre, parent_id):
    res = service.files().list(
        q=f"name='{nombre}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id)"
    ).execute()

    if res["files"]:
        return res["files"][0]["id"]

    folder = service.files().create(
        body={
            "name": nombre,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        },
        fields="id"
    ).execute()

    return folder["id"]

def subir_a_drive(service, file_buffer, file_name, folder_id):
    media = MediaIoBaseUpload(file_buffer, mimetype=MIME_DOCX, resumable=True)

    archivo = service.files().create(
        body={"name": file_name, "parents": [folder_id]},
        media_body=media,
        fields="id, webViewLink"
    ).execute()

    service.permissions().create(
        fileId=archivo["id"],
        body={"type": "anyone", "role": "reader"}
    ).execute()

    return archivo.get("webViewLink")

# ── CLAUDE ─────────────────────────────────────────────

def call_claude(prompt):
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 6000,
            "messages": [{"role": "user", "content": prompt}]
        }
    )

    data = response.json()

    if "content" not in data:
        raise Exception(f"Error Claude: {data}")

    return data["content"][0]["text"]

def generar_cv_adaptado(cv_master, empresa, puesto, descripcion):
    prompt = f"""
CV Master:
{cv_master}

Genera un CV adaptado para:
Empresa: {empresa}
Puesto: {puesto}
Descripción: {descripcion}
"""
    return call_claude(prompt)

# ── DOCX EN MEMORIA ───────────────────────────────────

def generar_docx_buffer(cv_texto):
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)

    for linea in cv_texto.split("\n"):
        if linea.strip():
            p = doc.add_paragraph(linea.strip())
            if p.runs:
                p.runs[0].font.size = Pt(10)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    return buffer

# ── CORE ─────────────────────────────────────────────

def generar_y_subir_cv(empresa, puesto, descripcion):
    try:
        service = get_drive_service()

        cv_master = leer_cv_master(service)

        cv = generar_cv_adaptado(cv_master, empresa, puesto, descripcion)

        fecha = datetime.now().strftime("%Y-%m-%d")
        empresa_slug = re.sub(r'[^a-zA-Z0-9]', '-', empresa)
        puesto_slug = re.sub(r'[^a-zA-Z0-9]', '-', puesto)

        folder_name = f"{fecha}_{empresa_slug}_{puesto_slug}"
        file_name   = f"CV_{empresa_slug}.docx"

        buffer = generar_docx_buffer(cv)

        folder_id = FOLDER_GENERADOS

        link = subir_a_drive(service, buffer, file_name, folder_id)

        return {
            "success": True,
            "link": link
        }

    except Exception as e:
        print("ERROR:", e)
        return {
            "success": False,
            "error": str(e)
        }

# ── API ─────────────────────────────────────────────

@app.route('/generar-cv', methods=['POST'])
def generar_cv():
    data = request.get_json()

    result = generar_y_subir_cv(
        data.get("empresa", ""),
        data.get("puesto", ""),
        data.get("descripcion", "")
    )

    return jsonify(result)

@app.route('/health')
def health():
    return {"status": "ok"}

# ── RUN ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)