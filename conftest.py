"""Config de tests.

`cv_server_railway` lee variables de entorno REQUERIDAS al importarse
(GROQ_API_KEY, NOTION_TOKEN, GOOGLE_*). En tests seteamos valores dummy
para poder importar el módulo sin credenciales reales; los tests mockean
los helpers/core, así que nunca se llama a servicios externos.
"""
import os

for _k in (
    "GROQ_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "NOTION_TOKEN",
):
    os.environ.setdefault(_k, "test-dummy")
