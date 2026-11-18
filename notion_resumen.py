"""Resumen operativo de ofertas pendientes del CRM de Notion (Spec 002).

Solo lectura: consulta la base de ofertas, filtra las que están en estado
"Pendiente" y las devuelve como lista de dicts y como Markdown legible.
No modifica Notion ni envía correo. Fail-closed ante errores.
"""
import logging
import time

import requests

from notion import NOTION_DB_OFERTAS, notion_headers

logger = logging.getLogger(__name__)

ESTADO_PENDIENTE = "Pendiente"
MAX_REINTENTOS = 4
TIMEOUT_S = 30


def _propiedad_texto(props: dict, nombre: str) -> str:
    prop = props.get(nombre) or {}
    tipo = prop.get("type")
    if tipo in ("title", "rich_text"):
        return "".join(t.get("plain_text", "") for t in prop.get(tipo) or []).strip()
    if tipo == "select":
        return (prop.get("select") or {}).get("name", "") or ""
    if tipo == "url":
        return prop.get("url") or ""
    if tipo == "date":
        return (prop.get("date") or {}).get("start", "") or ""
    if tipo in ("email", "phone_number"):
        return prop.get(tipo) or ""
    return ""


def _consultar_pagina(cursor: str | None) -> dict:
    """Una página de la query a la DB de ofertas. Reintenta lo pasajero."""
    cuerpo = {
        "filter": {"property": "Estado", "select": {"equals": ESTADO_PENDIENTE}},
        "page_size": 100,
    }
    if cursor:
        cuerpo["start_cursor"] = cursor
    ultimo = None
    for intento in range(MAX_REINTENTOS):
        try:
            resp = requests.post(
                f"https://api.notion.com/v1/databases/{NOTION_DB_OFERTAS}/query",
                headers=notion_headers(),
                json=cuerpo,
                timeout=TIMEOUT_S,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(1 * (intento + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            ultimo = e
            time.sleep(1 * (intento + 1))
    raise RuntimeError(f"Notion no responde tras {MAX_REINTENTOS} intentos: {ultimo}")


def listar_ofertas_pendientes() -> list[dict]:
    """Lista ofertas con Estado='Pendiente'. Solo lectura. Lanza RuntimeError si falla."""
    if not NOTION_DB_OFERTAS:
        raise RuntimeError("NOTION_DB_OFERTAS no configurado")
    salida = []
    cursor = None
    while True:
        data = _consultar_pagina(cursor)
        for page in data.get("results", []) or []:
            props = page.get("properties", {}) or {}
            oferta = {
                "id": page.get("id", ""),
                "empresa": _propiedad_texto(props, "Empresa"),
                "puesto": _propiedad_texto(props, "Puesto"),
                "ubicacion": _propiedad_texto(props, "Ubicación"),
                "modalidad": _propiedad_texto(props, "Modalidad"),
                "salario": _propiedad_texto(props, "Salario"),
                "enlace": _propiedad_texto(props, "Link oferta"),
                "fecha_publicacion": _propiedad_texto(props, "Fecha Publicacion"),
                "via_envio": _propiedad_texto(props, "Via envio"),
                "notas": _propiedad_texto(props, "Notas"),
            }
            salida.append(oferta)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return salida


def es_incompleta(oferta: dict) -> bool:
    return not (oferta.get("empresa") or "").strip() or not (oferta.get("puesto") or "").strip()


def resumen_pendientes_markdown(ofertas: list[dict]) -> str:
    """Convierte la lista en un resumen Markdown legible. Marca las incompletas."""
    if not ofertas:
        return "## Ofertas pendientes\n\n_No hay ofertas pendientes._\n"
    lineas = ["## Ofertas pendientes", "", f"Total: {len(ofertas)}", ""]
    for i, o in enumerate(ofertas, 1):
        empresa = o.get("empresa") or "(sin empresa)"
        puesto = o.get("puesto") or "(sin puesto)"
        marca = " ⚠️ incompleta" if es_incompleta(o) else ""
        lineas.append(f"{i}. **{empresa}** — {puesto}{marca}")
        extras = []
        if o.get("ubicacion"):
            extras.append(f"ubicación: {o['ubicacion']}")
        if o.get("modalidad"):
            extras.append(f"modalidad: {o['modalidad']}")
        if o.get("salario"):
            extras.append(f"salario: {o['salario']}")
        if o.get("via_envio"):
            extras.append(f"vía: {o['via_envio']}")
        if extras:
            lineas.append("   " + " · ".join(extras))
        if o.get("enlace"):
            lineas.append(f"   enlace: {o['enlace']}")
        if o.get("notas"):
            lineas.append(f"   notas: {o['notas']}")
    incompletas = [o for o in ofertas if es_incompleta(o)]
    if incompletas:
        lineas.append("")
        lineas.append(f"_Ofertas incompletas (falta empresa o puesto): {len(incompletas)}_")
    return "\n".join(lineas) + "\n"

