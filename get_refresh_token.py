"""
Genera un GOOGLE_REFRESH_TOKEN nuevo para el cv-server.

Lee GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET del .env (mismo cliente que usa Render),
abre el navegador para que inicies sesion con la cuenta de Google DUENA del Drive,
y al final imprime el refresh token nuevo.

USO:
    pip install google-auth-oauthlib python-dotenv
    python get_refresh_token.py

Despues: pega el token impreso en Render -> cv-server -> Environment -> GOOGLE_REFRESH_TOKEN
y redeploy.
"""
import os
import sys
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()  # lee el .env de esta carpeta

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("ERROR: faltan GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET en el .env")

# Mismo scope que usa el cv-server (acceso total a Drive del usuario)
SCOPES = ["https://www.googleapis.com/auth/drive"]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

# access_type=offline + prompt=consent => garantiza que Google devuelva refresh_token
creds = flow.run_local_server(
    port=8080,
    access_type="offline",
    prompt="select_account consent",
)

print("\n" + "=" * 60)
print("REFRESH TOKEN NUEVO (copialo entero):")
print("=" * 60)
print(creds.refresh_token)
print("=" * 60)
print("\nPegalo en Render -> cv-server -> Environment -> GOOGLE_REFRESH_TOKEN y redeploy.")
