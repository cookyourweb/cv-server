#!/usr/bin/env python3
"""
Script para obtener el refresh token de Google OAuth.
Ejecutar localmente una vez para obtener las credenciales.
"""

from google_auth_oauthlib.flow import InstalledAppFlow
import json

SCOPES = ["https://www.googleapis.com/auth/drive"]

# Pegá acá el contenido del client_secret.json que descargaste de Google Cloud
CLIENT_CONFIG = {
    "installed": {
        "client_id": "TU_CLIENT_ID_ACA",
        "project_id": "TU_PROJECT_ID",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": ["http://localhost"],
        "client_secret": "TU_CLIENT_SECRET_ACA"
    }
}

def main():
    flow = InstalledAppFlow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES
    )

    creds = flow.run_local_server(port=0)

    print("\n" + "="*50)
    print("COPIA ESTOS VALORES PARA RAILWAY/RENDER:")
    print("="*50)
    print(f"GOOGLE_CLIENT_ID={creds.client_id}")
    print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("="*50)

if __name__ == "__main__":
    main()
