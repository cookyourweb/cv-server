"""Offer match routes: GET /ofertas/{id}/encaje and POST /encajes (C13, ADR-009).

Behind `@con_usuaria`. The match itself is `match.evaluar` (pure, rule based, no model
call). What this module adds is WHO may ask for what:

- An offer is the caller's only if its Notion "Usuario" relation holds her Notion page
  id (found by her verified email). Not hers, nobody's, missing, malformed: all the same
  404 with the same body, so the route is no existence oracle. In a batch such ids are
  silently left out.
- Notion errors fail closed with a generic 503: never a guess, never another user's data.
- The profile comes from her own rows and the master from `fuente_master.resolver_master`,
  which already enforces the `enviar_cv_a_ia` consent for a stored master.
- The response is the match and nothing else: no CV text beyond the short evidence
  snippets `match.py` builds (REQ-6.5). Nothing logs an email, an id or CV text.
"""
import logging

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

import base_de_datos
import fuente_master
import match
import notion
import privacidad
from repositorio import RepositorioDeUsuaria

logger = logging.getLogger(__name__)

MAX_IDS = 50
MAX_LARGO_ID = 64
IDIOMAS = ("es", "en")

_NO_ENCONTRADO = ({"ok": False, "error": "no encontrado"}, 404)
_NO_DISPONIBLE = ({"ok": False, "error": "servicio no disponible"}, 503)
_SIN_NADA = ({"ok": False, "error": "falta el perfil y el master", "motivo": "sin_perfil_ni_master"}, 409)
_DATOS_NO_VALIDOS = ({"ok": False, "error": "datos no validos", "campos": ["ids"]}, 422)


class _Respuesta(Exception):
    """Carries an already built (body, status) out of a helper."""

    def __init__(self, cuerpo_y_estado):
        self.cuerpo_y_estado = cuerpo_y_estado


def _responder(cuerpo_y_estado):
    cuerpo, estado = cuerpo_y_estado
    return jsonify(cuerpo), estado


def _perfil_de(usuario_id):
    """Her profile in the wire format, or None (also without a database: legacy mode)."""
    if usuario_id is None or not base_de_datos.configurada():
        return None
    with base_de_datos.transaccion() as conexion:
        return RepositorioDeUsuaria(conexion, usuario_id).obtener_perfil()


def _usuario_notion(email: str):
    """Her Notion record, or None when she has none. Raises _Respuesta(503) on any failure."""
    try:
        usuario = notion.buscar_usuario_por_email(email)
    except Exception as error:  # fail closed whatever it was; never leak its message
        privacidad.registrar_fallo(logger, "notion user lookup failed in the match", error)
        raise _Respuesta(_NO_DISPONIBLE)
    if usuario is None and not notion.NOTION_DB_USUARIOS:
        raise _Respuesta(_NO_DISPONIBLE)  # unconfigured is not "she owns nothing"
    return usuario


def _ofertas_propias(ids) -> tuple:
    """(usuario Notion, {plain id: offer}) for the ids that belong to the caller."""
    usuario = _usuario_notion(g.identidad.email)
    notion_id = (usuario or {}).get("notion_id") or ""
    if not notion_id:
        return usuario, {}
    try:
        return usuario, notion.leer_ofertas_de_usuaria(ids, notion_id)
    except notion.ErrorDeNotion as error:
        privacidad.registrar_fallo(logger, "notion offers lookup failed in the match", error)
        raise _Respuesta(_NO_DISPONIBLE)


def _texto_de(oferta: dict) -> str:
    return "\n".join(p for p in (oferta.get("puesto"), oferta.get("descripcion"),
                                 " ".join(oferta.get("tags") or [])) if p)


def _evaluar(usuario: dict, propias: dict) -> dict:
    """{plain id: match dict} for every offer in `propias`. Raises _Respuesta (409/503)."""
    try:
        perfil = _perfil_de(g.usuario_id)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        privacidad.registrar_fallo(logger, "database error in the match", error)
        raise _Respuesta(_NO_DISPONIBLE)
    masters = {}  # one read per language, not per offer
    for oferta in propias.values():
        idioma = oferta.get("idioma") if oferta.get("idioma") in IDIOMAS else "es"
        if idioma in masters:
            continue
        try:
            masters[idioma] = fuente_master.resolver_master(usuario, idioma, g.identidad.email).texto
        except Exception as error:  # Drive, decryption...: fail closed, never leak the message
            privacidad.registrar_fallo(logger, "master lookup failed in the match", error)
            raise _Respuesta(_NO_DISPONIBLE)
    if perfil is None and not any(masters.values()):
        raise _Respuesta(_SIN_NADA)
    resultado = {}
    for clave, oferta in propias.items():
        idioma = oferta.get("idioma") if oferta.get("idioma") in IDIOMAS else "es"
        resultado[clave] = match.evaluar(_texto_de(oferta), perfil or {}, masters[idioma]).a_dict()
    return resultado


def _ids_de_la_peticion():
    cuerpo = request.get_json(silent=True)
    ids = cuerpo.get("ids") if isinstance(cuerpo, dict) else None
    if (not isinstance(ids, list) or len(ids) > MAX_IDS
            or not all(isinstance(i, str) and len(i) <= MAX_LARGO_ID for i in ids)):
        raise _Respuesta(_DATOS_NO_VALIDOS)
    return ids


def crear_blueprint(con_usuaria) -> Blueprint:
    encaje = Blueprint("encaje", __name__)

    @encaje.get("/ofertas/<oferta_id>/encaje")
    @con_usuaria
    def encaje_de_oferta(oferta_id):
        try:
            usuario, propias = _ofertas_propias([oferta_id])
            if not propias:
                return _responder(_NO_ENCONTRADO)
            return jsonify(next(iter(_evaluar(usuario, propias).values()))), 200
        except _Respuesta as r:
            return _responder(r.cuerpo_y_estado)

    @encaje.post("/encajes")
    @con_usuaria
    def encajes():
        try:
            ids = _ids_de_la_peticion()
            usuario, propias = _ofertas_propias(ids)
            if not propias:
                return jsonify({}), 200
            resultado = _evaluar(usuario, propias)
        except _Respuesta as r:
            return _responder(r.cuerpo_y_estado)
        # Keyed by the id exactly as the caller sent it (the panel looks results up by its own
        # ids). Only the summary travels: no requirements, gaps or evidence on the wire.
        # If one offer comes in two spellings, it is answered once, under the first spelling.
        salida, vistos = {}, set()
        for id_pedido in ids:  # ids that are not hers vanish
            clave = notion.normalizar_id(id_pedido)
            if clave in resultado and clave not in vistos:
                vistos.add(clave)
                salida[id_pedido] = {"alcanzable": resultado[clave]["alcanzable"],
                                     "cobertura": resultado[clave]["cobertura"]}
        return jsonify(salida), 200

    return encaje
