"""
Regenera el GOOGLE_REFRESH_TOKEN, lo guarda en .env, y VERIFICA que funciona
(refresh + lectura del CV master) en un solo paso.

USO (con venv activado):
    python regenera_token.py

Al final: si dice TODO OK, copiás el token impreso a Render y redeploy.
"""
import os
import re
import traceback
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

ENV_PATH = Path(__file__).with_name(".env")
load_dotenv(ENV_PATH)

CID = os.environ.get("GOOGLE_CLIENT_ID")
CSEC = os.environ.get("GOOGLE_CLIENT_SECRET")
if not CID or not CSEC:
    raise SystemExit("ERROR: faltan GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET en .env")

SCOPES = ["https://www.googleapis.com/auth/drive"]
client_config = {
    "installed": {
        "client_id": CID,
        "client_secret": CSEC,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

print("=" * 60)
print("1) LOGIN — entrá con la cuenta DUEÑA del Drive (CV masters)")
print("=" * 60)
flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
creds = flow.run_local_server(port=8080, access_type="offline", prompt="select_account consent")
new_token = creds.refresh_token
if not new_token:
    raise SystemExit("ERROR: Google no devolvió refresh_token. Reintentá (revocá el acceso antiguo en myaccount.google.com/permissions).")

# --- Guardar en .env (reemplaza la línea o la añade) ---
text = ENV_PATH.read_text() if ENV_PATH.exists() else ""
line = f"GOOGLE_REFRESH_TOKEN={new_token}"
if re.search(r"^GOOGLE_REFRESH_TOKEN=.*$", text, flags=re.M):
    text = re.sub(r"^GOOGLE_REFRESH_TOKEN=.*$", line, text, flags=re.M)
else:
    text = text.rstrip("\n") + "\n" + line + "\n"
ENV_PATH.write_text(text)
print(f"\n  ✅ Token guardado en {ENV_PATH}")

# --- Verificar refresh + lectura del master ---
print("\n" + "=" * 60)
print("2) VERIFICANDO el token nuevo")
print("=" * 60)
FILE_ID = "1hYSwJHWRMU47jkud2bWh_mY6LGr-Nec5ST9Z72iZMqQ"  # CV Master URL ES
try:
    c2 = Credentials(token=None, refresh_token=new_token,
                     token_uri="https://oauth2.googleapis.com/token",
                     client_id=CID, client_secret=CSEC, scopes=SCOPES)
    c2.refresh(Request())
    print("  ✅ REFRESH OK")
    service = build("drive", "v3", credentials=c2)
    meta = service.files().get(fileId=FILE_ID, fields="name, mimeType", supportsAllDrives=True).execute()
    print(f"  ✅ LEE EL MASTER: '{meta.get('name')}' ({meta.get('mimeType')})")
    print("\n" + "=" * 60)
    print("TODO OK. Copiá este token a Render y redeploy:")
    print("=" * 60)
    print(new_token)
    print("=" * 60)
    print("Render -> cv-server -> Environment -> GOOGLE_REFRESH_TOKEN -> pegar -> Save -> Redeploy")
except Exception:
    print("  ❌ El token nuevo TAMPOCO funciona. Error:\n")
    traceback.print_exc()
    print("\n>>> Si es invalid_grant otra vez: la app OAuth sigue en 'Testing'.")
    print("    Publicala a Producción (Paso 1) y volvé a correr esto.")
    print(">>> Si es error de permiso sobre el archivo: entraste con OTRA cuenta,")
    print("    no la dueña del CV master. Reintentá con la cuenta correcta.")
