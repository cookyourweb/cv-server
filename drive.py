"""Google Drive: subir el CV generado y leer el CV Master.

Dos operaciones y la eleccion de cual Master toca segun el idioma. Se autentica
con OAuth de usuario (refresh token), no con cuenta de servicio.

Lee sus credenciales del entorno igual que el servidor: no importa nada de
`server`. Extraido el 28-ago-2026.
"""
import io
import logging
import os
import re
from typing import NamedTuple

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")
FOLDER_CV_MASTERS = os.getenv("FOLDER_CV_MASTERS", "1duJA_G3lLbOqiUYoSJcsXAvbtJUdcmzR")
FOLDER_CV_GENERADOS = os.getenv("FOLDER_CV_GENERADOS", "1tHuVOIz3ratjRp8AmHsF0kGVpmy9DocY")

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
        "parents": [FOLDER_CV_GENERADOS],
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


# ── Guardrail de veracidad: cifras inventadas ────
# El prompt YA prohibe inventar metricas y el modelo lo hizo igual (caso real:
# "serving millions of users", cifra que no existe en el Master). Una instruccion
# es una peticion, no una garantia: la salida se VERIFICA contra la fuente.

class MasterElegido(NamedTuple):
    """Master seleccionado para un idioma, con la URL de la que sale.

    Sin la url no se puede reportar CUAL master se usó: la respuesta acababa
    devolviendo siempre el master inglés aunque el CV fuese en español.
    """
    file_id: str
    url:     str


def elegir_master(usuario: dict, idioma: str) -> MasterElegido:
    """Elige la fuente del master segun el idioma. Pura: no toca Drive.
    idioma='en' -> 'CV Master URL' (ingles); cualquier otro -> 'CV Master URL ES'
    (con fallback al master ingles si no hay version española configurada)."""
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
        m = re.search(r'/d/([a-zA-Z0-9_-]+)', url) or re.search(r'id=([a-zA-Z0-9_-]+)', url)
        if m:
            file_id = m.group(1)

    return MasterElegido(file_id, url)


class MasterCV(NamedTuple):
    """Texto del master y la URL de la que se leyó de verdad."""
    texto: str
    url:   str


def leer_cv_master_desde_drive(usuario: dict, idioma: str = "es") -> MasterCV:
    """Descarga el CV master en texto plano desde Drive, eligiendo la fuente segun idioma."""
    service = get_drive_service()

    file_id, url = elegir_master(usuario, idioma)

    if not file_id:
        return MasterCV("", "")

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
            return MasterCV("\n".join(partes), url)

        # Texto plano u otros formatos legibles
        return MasterCV(buf.read().decode("utf-8", errors="replace"), url)
    except Exception as e:
        logger.warning("No se pudo leer CV master (file_id=%s): %s", file_id, e)
        return MasterCV("", url)
