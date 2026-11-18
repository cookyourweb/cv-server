"""Core puro (sin Flask/FastAPI) del match de ofertas (encaje).

Mueve la lógica de `rutas_encaje.py` a funciones parametrizadas por
`usuario_id` y `email` (sin `g` global), para que sirvan en Flask y FastAPI.
Ver docs/ADR-001 y docs/plan-core-extraction-7-endpoints.md.
"""
import logging
from typing import Any

import base_de_datos
import fuente_master
import match
import notion
import privacidad
from errores import CVError
from repositorio import RepositorioDeUsuaria
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

MAX_LARGO_ID = 64
IDIOMAS = ("es", "en")

_NO_ENCONTRADO = ({"ok": False, "error": "no encontrado"}, 404)
_NO_DISPONIBLE = ({"ok": False, "error": "servicio no disponible"}, 503)
_SIN_NADA = ({"ok": False, "error": "falta el perfil y el master", "motivo": "sin_perfil_ni_master"}, 409)


def _usuario_notion(email: str):
    """Her Notion record, or None. Raises CVError(503) on any failure."""
    try:
        usuario = notion.buscar_usuario_por_email(email)
    except Exception as error:
        privacidad.registrar_fallo(logger, "notion user lookup failed in the match", error)
        raise CVError(503, "servicio no disponible")
    if usuario is None and not notion.NOTION_DB_USUARIOS:
        raise CVError(503, "servicio no disponible")
    return usuario


def _ofertas_propias(usuario_notion_id: str, ids: list[str]) -> dict:
    """{plain id: offer} for the ids that belong to the caller. Empty if none."""
    if not usuario_notion_id:
        return {}
    try:
        return notion.leer_ofertas_de_usuaria(ids, usuario_notion_id)
    except notion.ErrorDeNotion as error:
        privacidad.registrar_fallo(logger, "notion offers lookup failed in the match", error)
        raise CVError(503, "servicio no disponible")


def _perfil_de(usuario_id):
    """Her profile in wire format, or None (legacy mode without DB)."""
    if usuario_id is None or not base_de_datos.configurada():
        return None
    with base_de_datos.transaccion() as conexion:
        return RepositorioDeUsuaria(conexion, usuario_id).obtener_perfil()


def _texto_de(oferta: dict) -> str:
    return "\n".join(p for p in (oferta.get("puesto"), oferta.get("descripcion"),
                                 " ".join(oferta.get("tags") or [])) if p)


def encaje_de_oferta_core(usuario_id, email: str, oferta_id: str) -> dict:
    """Match de una oferta vs perfil/master de la usuaria. Lanza CVError en errores."""
    if len(oferta_id) > MAX_LARGO_ID:
        raise CVError(404, "no encontrado")

    usuario = _usuario_notion(email)
    notion_id = (usuario or {}).get("notion_id") or ""
    propias = _ofertas_propias(notion_id, [oferta_id])
    if not propias:
        raise CVError(404, "no encontrado")

    # profile + master (one read per language)
    try:
        perfil = _perfil_de(usuario_id)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        privacidad.registrar_fallo(logger, "database error in the match", error)
        raise CVError(503, "servicio no disponible")

    masters = {}
    for oferta in propias.values():
        idioma = oferta.get("idioma") if oferta.get("idioma") in IDIOMAS else "es"
        if idioma in masters:
            continue
        try:
            masters[idioma] = fuente_master.resolver_master(usuario, idioma, email).texto
        except Exception as error:
            privacidad.registrar_fallo(logger, "master lookup failed in the match", error)
            raise CVError(503, "servicio no disponible")

    if perfil is None and not any(masters.values()):
        raise CVError(409, "falta el perfil y el master", extra={"motivo": "sin_perfil_ni_master"})

    resultado = {}
    for clave, oferta in propias.items():
        idioma = oferta.get("idioma") if oferta.get("idioma") in IDIOMAS else "es"
        resultado[clave] = match.evaluar(_texto_de(oferta), perfil or {}, masters[idioma]).a_dict()

    # Devuelve el match de la unica oferta (keyed por id normalizado).
    return list(resultado.values())[0] if resultado else {}


def encajes_batch_core(usuario_id, email: str, ids: list) -> dict:
    """Match en batch (hasta 50 ids). Valida entrada, omite silenciosamente no-propias."""
    if (not isinstance(ids, list) or len(ids) > 50
            or not all(isinstance(i, str) and len(i) <= MAX_LARGO_ID for i in ids)):
        raise CVError(422, "datos no validos", extra={"campos": ["ids"]})

    usuario = _usuario_notion(email)
    notion_id = (usuario or {}).get("notion_id") or ""
    propias = _ofertas_propias(notion_id, ids)
    if not propias:
        return {}

    try:
        perfil = _perfil_de(usuario_id)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        privacidad.registrar_fallo(logger, "database error in the match", error)
        raise CVError(503, "servicio no disponible")

    masters = {}
    for oferta in propias.values():
        idioma = oferta.get("idioma") if oferta.get("idioma") in IDIOMAS else "es"
        if idioma in masters:
            continue
        try:
            masters[idioma] = fuente_master.resolver_master(usuario, idioma, email).texto
        except Exception as error:
            privacidad.registrar_fallo(logger, "master lookup failed in the match", error)
            raise CVError(503, "servicio no disponible")

    if perfil is None and not any(masters.values()):
        raise CVError(409, "falta el perfil y el master", extra={"motivo": "sin_perfil_ni_master"})

    resultado_por_clave = {}
    for clave, oferta in propias.items():
        idioma = oferta.get("idioma") if oferta.get("idioma") in IDIOMAS else "es"
        resultado_por_clave[clave] = match.evaluar(_texto_de(oferta), perfil or {}, masters[idioma]).a_dict()

    # Salida keyed por id tal como se envió (dedup por id normalizado).
    salida = {}
    vistos = set()
    for i in ids:
        # normalizar como en notion.normalizar_id
        nid = i.replace("-", "").lower()
        if nid in vistos:
            continue
        vistos.add(nid)
        if nid in resultado_por_clave:
            salida[i] = resultado_por_clave[nid]
    # Fallback: si la normalización no coincide, devolver por clave original.
    if not salida and resultado_por_clave:
        for k, v in resultado_por_clave.items():
            salida[k] = v
    return salida

