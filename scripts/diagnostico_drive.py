"""
Diagnóstico Drive del cv-server. Reproduce get_drive_service() + lectura del
CV master mostrando el ERROR EXACTO. No imprime el token (secreto).

USO (con el venv activado):
    python diagnostico_drive.py
"""
import os
import traceback
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

CID = os.environ.get("GOOGLE_CLIENT_ID", "")
CSEC = os.environ.get("GOOGLE_CLIENT_SECRET", "")
RTOK = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

print("=" * 60)
print("1) VARIABLES EN .env")
print("=" * 60)
print(f"  GOOGLE_CLIENT_ID     : {'OK ('+CID[:12]+'...)' if CID else '✗ FALTA'}")
print(f"  GOOGLE_CLIENT_SECRET : {'OK' if CSEC else '✗ FALTA'}")
print(f"  GOOGLE_REFRESH_TOKEN : {'OK (termina en ...'+RTOK[-6:]+', largo='+str(len(RTOK))+')' if RTOK else '✗ FALTA'}")

if not (CID and CSEC and RTOK):
    raise SystemExit("\n>>> Faltan credenciales en .env. Ese es el problema.")

print("\n" + "=" * 60)
print("2) REFRESCAR EL TOKEN (lo que crashea el server)")
print("=" * 60)
creds = Credentials(
    token=None,
    refresh_token=RTOK,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=CID,
    client_secret=CSEC,
    scopes=["https://www.googleapis.com/auth/drive"],
)
try:
    creds.refresh(Request())
    print("  ✅ REFRESH OK — el token es válido y la cuenta autoriza.")
except Exception as e:
    print("  ❌ REFRESH FALLÓ. Este es el error real del 500:\n")
    traceback.print_exc()
    raise SystemExit("\n>>> El problema es el TOKEN/permiso OAuth (ver error arriba).")

print("\n" + "=" * 60)
print("3) LEER EL CV MASTER ES desde Drive")
print("=" * 60)
FILE_ID = "1hYSwJHWRMU47jkud2bWh_mY6LGr-Nec5ST9Z72iZMqQ"  # CV Master URL ES
try:
    service = build("drive", "v3", credentials=creds)
    meta = service.files().get(fileId=FILE_ID, fields="name, mimeType", supportsAllDrives=True).execute()
    print(f"  ✅ ACCESO OK — '{meta.get('name')}' ({meta.get('mimeType')})")
    print("\n>>> Drive funciona. Si el server sigue en 500, el token de RENDER")
    print("    es distinto del de tu .env: hay que copiar ESTE token a Render.")
except Exception as e:
    print("  ❌ NO PUEDO LEER EL MASTER. Error:\n")
    traceback.print_exc()
    print("\n>>> El token refresca pero NO tiene permiso sobre ese documento")
    print("    (cuenta equivocada, o el doc no es de esta cuenta).")
