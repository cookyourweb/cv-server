"""Owner-scoped routes of the sign-up flow: /perfil, /consentimientos, /cv and /cuenta.

Every route runs behind `@con_usuaria`, which resolves the caller to `g.usuario_id`;
the data comes only from `RepositorioDeUsuaria(conexion, g.usuario_id)`, so there is no
path or body field that names another user (REQ-1.4). The wire format is the panel's:
snake_case fields, 404 when there is no profile, 201 for a recorded consent.

Without DATABASE_URL (production until the database exists) every route answers a
generic 503; `/yo` and `/health` do not depend on it. Errors never carry submitted
values, driver messages or connection details.
"""
import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError

import base_de_datos
import privacidad
from cifrado import ErrorDeCifrado, cifrar
from lectura_cv import LIMITE_BYTES, ErrorDeLectura, leer_cv
from repositorio import ConsentimientoEntrada, PerfilEntrada, RepositorioDeUsuaria

logger = logging.getLogger(__name__)

_NO_ENCONTRADO = ({"ok": False, "error": "no encontrado"}, 404)
_NO_DISPONIBLE = ({"ok": False, "error": "servicio no disponible"}, 503)
_SIN_CONSENTIMIENTO = ({"ok": False, "error": "consentimiento necesario"}, 403)

# How a CV that cannot be used is reported: (status, fixed message). The panel maps the
# status (413 size, 415 type, 422 unreadable); `motivo` lets it tell a scan from a corrupt file.
_RECHAZOS_DE_CV = {
    "tamano": (413, "archivo demasiado grande"),
    "tipo": (415, "tipo de archivo no admitido"),
    "ilegible": (422, "no se pudo leer el archivo"),
    "largo": (422, "el archivo es demasiado largo"),
    "sin_texto": (422, "el archivo no tiene texto"),
}
IDIOMAS = ("es", "en")


def _rechazo_de_cv(motivo: str):
    estado, mensaje = _RECHAZOS_DE_CV[motivo]
    return _respuesta(({"ok": False, "error": mensaje, "motivo": motivo}, estado))


def _respuesta(cuerpo_y_estado):
    cuerpo, estado = cuerpo_y_estado
    return jsonify(cuerpo), estado


def _con_repositorio(vista):
    """Open one transaction for the request and hand the view an owner-scoped repository."""
    @wraps(vista)
    def envuelta(*args, **kwargs):
        if g.usuario_id is None or not base_de_datos.configurada():
            return _respuesta(_NO_DISPONIBLE)
        try:
            with base_de_datos.transaccion() as conexion:
                return vista(RepositorioDeUsuaria(conexion, g.usuario_id), *args, **kwargs)
        except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
            logger.error("database error in %s: %s", request.endpoint, type(error).__name__)
            return _respuesta(_NO_DISPONIBLE)
    return envuelta


def _leer(modelo: type[BaseModel]):
    """The validated body, or a 422 response. Reports field names, never values."""
    cuerpo = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        return None, _respuesta(({"ok": False, "error": "datos no validos", "campos": []}, 422))
    try:
        return modelo(**cuerpo), None
    except ValidationError as error:
        campos = sorted({str(e["loc"][0]) for e in error.errors()
                         if e["loc"] and str(e["loc"][0]) in modelo.model_fields})
        return None, _respuesta(({"ok": False, "error": "datos no validos", "campos": campos}, 422))


def crear_blueprint(con_usuaria) -> Blueprint:
    """Build the blueprint around the `@con_usuaria` decorator of the running app."""
    alta = Blueprint("alta", __name__)

    @alta.get("/perfil")
    @con_usuaria
    @_con_repositorio
    def leer_perfil(repo):
        perfil = repo.obtener_perfil()
        return _respuesta(_NO_ENCONTRADO) if perfil is None else (jsonify(perfil), 200)

    @alta.put("/perfil")
    @con_usuaria
    @_con_repositorio
    def guardar_perfil(repo):
        perfil, error = _leer(PerfilEntrada)
        if error:
            return error
        repo.guardar_perfil(perfil)
        return jsonify(repo.obtener_perfil()), 200

    @alta.post("/consentimientos")
    @con_usuaria
    @_con_repositorio
    def registrar_consentimiento(repo):
        consentimiento, error = _leer(ConsentimientoEntrada)
        if error:
            return error
        repo.registrar_consentimiento(consentimiento.tipo, consentimiento.version)
        return jsonify({"tipo": consentimiento.tipo, "version": consentimiento.version}), 201

    @alta.errorhandler(413)
    def peticion_demasiado_grande(_error):
        # Flask refuses the body (MAX_CONTENT_LENGTH) before the upload is read.
        return _rechazo_de_cv("tamano")

    @alta.post("/cv")
    @con_usuaria
    @_con_repositorio
    def subir_cv(repo):
        # Consent first: a CV of someone who has not agreed to store it is not even parsed.
        if not repo.tiene_consentimiento("almacenar_cv"):
            return _respuesta(_SIN_CONSENTIMIENTO)
        archivo = request.files.get("archivo")
        if archivo is None:
            return _respuesta(({"ok": False, "error": "falta el archivo"}, 422))
        try:
            leido = leer_cv(archivo.read(LIMITE_BYTES + 1))
        except ErrorDeLectura as error:
            return _rechazo_de_cv(error.codigo)
        try:
            version, nonce, protegido = cifrar(leido.texto, g.usuario_id, leido.idioma)
        except ErrorDeCifrado as error:
            privacidad.registrar_fallo(logger, "cv encryption unavailable", error)
            return _respuesta(_NO_DISPONIBLE)
        # Only the encrypted text is stored; the uploaded file itself is dropped here (REQ-3.4).
        repo.guardar_cv(leido.idioma, leido.formato, version, nonce, protegido, leido.caracteres)
        return jsonify({"idioma": leido.idioma, "formato": leido.formato, "caracteres": leido.caracteres}), 201

    @alta.get("/cv")
    @con_usuaria
    @_con_repositorio
    def listar_cvs(repo):
        return jsonify(repo.listar_cvs()), 200

    @alta.delete("/cv/<idioma>")
    @con_usuaria
    @_con_repositorio
    def borrar_cv(repo, idioma):
        return ("", 204) if idioma in IDIOMAS and repo.borrar_cv(idioma) else _respuesta(_NO_ENCONTRADO)

    @alta.delete("/cuenta")
    @con_usuaria
    @_con_repositorio
    def borrar_cuenta(repo):
        # One transaction (opened by _con_repositorio): it commits only if every step
        # succeeded, so a failure midway leaves the account exactly as it was (REQ-2.3).
        return ("", 204) if repo.borrar_cuenta() else _respuesta(_NO_ENCONTRADO)

    return alta
