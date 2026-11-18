"""Core puro (sin Flask/FastAPI) de las rutas de alta: CV, extracción, kill switch.

Cada función lanza CVError en los errores. La capa HTTP (Flask/FastAPI) solo
parsea la entrada, llama al core y mapea CVError a su formato de respuesta.
Ver docs/ADR-001 y docs/plan-core-extraction-7-endpoints.md.
"""
import logging

import base_de_datos
import extraccion
import llm
import propuestas
from cifrado import ErrorDeCifrado, cifrar, descifrar
from errores import CVError
from lectura_cv import ErrorDeLectura, LIMITE_BYTES, leer_cv
from privacidad import registrar_fallo
from repositorio import RepositorioDeUsuaria
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

IDIOMAS = ("es", "en")


def fijar_extraccion_core(activa: bool) -> dict:
    """Turn the extraction kill switch on/off. Returns {"activa": activa}.

    Lanza CVError(503) si la BD no está configurada o falla.
    """
    if not base_de_datos.configurada():
        raise CVError(503, "servicio no disponible")
    try:
        with base_de_datos.transaccion() as conexion:
            extraccion.fijar_interruptor(conexion, activa)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        logger.error("database error setting the extraction switch: %s", type(error).__name__)
        raise CVError(503, "servicio no disponible")
    return {"activa": activa}


def listar_cvs_core(usuario_id) -> list:
    """Lista los CVs guardados (solo metadatos, nunca contenido). Lanza CVError(503) sin BD/usuario."""
    if usuario_id is None or not base_de_datos.configurada():
        raise CVError(503, "servicio no disponible")
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        return repo.listar_cvs()


def borrar_cv_core(usuario_id, idioma: str) -> None:
    """Borra el CV del idioma indicado. Lanza CVError(404) si idioma inválido o no existe."""
    if idioma not in IDIOMAS:
        raise CVError(404, "no encontrado")
    if usuario_id is None or not base_de_datos.configurada():
        raise CVError(503, "servicio no disponible")
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        if not repo.borrar_cv(idioma):
            raise CVError(404, "no encontrado")


_RECHAZOS_DE_CV = {
    "tamano": (413, "archivo demasiado grande"),
    "tipo": (415, "tipo de archivo no admitido"),
    "ilegible": (422, "no se pudo leer el archivo"),
    "largo": (422, "el archivo es demasiado largo"),
    "sin_texto": (422, "el archivo no tiene texto"),
}


def subir_cv_core(usuario_id, contenido: bytes) -> dict:
    """Sube y cifra un CV. Lanza CVError en los errores.

    Consentimiento `almacenar_cv` se verifica ANTES de parsear el archivo.
    Devuelve {"idioma", "formato", "caracteres"}.
    """
    if usuario_id is None or not base_de_datos.configurada():
        raise CVError(503, "servicio no disponible")

    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        if not repo.tiene_consentimiento("almacenar_cv"):
            raise CVError(403, "consentimiento necesario")

    # Parsear fuera de la transacción (no mantenerla abierta durante I/O).
    try:
        leido = leer_cv(contenido)
    except ErrorDeLectura as error:
        estado, mensaje = _RECHAZOS_DE_CV.get(error.codigo, (422, "no se pudo leer el archivo"))
        raise CVError(estado, mensaje, extra={"motivo": error.codigo})

    try:
        version, nonce, protegido = cifrar(leido.texto, usuario_id, leido.idioma)
    except ErrorDeCifrado as error:
        registrar_fallo(logger, "cv encryption unavailable", error)
        raise CVError(503, "servicio no disponible")

    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        repo.guardar_cv(leido.idioma, leido.formato, version, nonce, protegido, leido.caracteres)

    return {"idioma": leido.idioma, "formato": leido.formato, "caracteres": leido.caracteres}


def _manual(motivo: str) -> dict:
    return {"estado": "manual", "motivo": motivo}


def extraer_perfil_core(usuario_id) -> dict:
    """Extracción owner-paid del perfil. Devuelve dict con estado manual/propuesta.

    Lanza CVError en errores de servicio/BD. Preserva el orden y la reserva de cuota.
    """
    if usuario_id is None or not base_de_datos.configurada():
        raise CVError(503, "servicio no disponible")

    with base_de_datos.transaccion() as conexion:
        if extraccion.desactivada(conexion):
            return _manual("desactivada")
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        if not repo.tiene_consentimiento("enviar_cv_a_ia"):
            raise CVError(403, "consentimiento necesario")
        guardado = repo.cv_mas_reciente()
    if guardado is None:
        raise CVError(404, "no encontrado")

    if not llm.clave_de_extraccion_configurada():
        return _manual("indisponible")

    modelo = llm.CV_MODEL
    reserva = extraccion.reservar(usuario_id, propuestas.largo_del_prompt(guardado.caracteres), modelo=modelo)
    if isinstance(reserva, extraccion.Rechazo):
        return _manual(reserva.motivo)

    cerrada = False
    try:
        try:
            texto = descifrar(guardado.clave_version, guardado.nonce, guardado.cifrado, usuario_id, guardado.idioma)
        except ErrorDeCifrado as error:
            registrar_fallo(logger, "cv decryption unavailable", error)
            raise CVError(503, "servicio no disponible")
        try:
            respuesta = llm.call_llm_extraccion(propuestas.construir_prompt(texto), model=modelo)
        except Exception as error:
            registrar_fallo(logger, "extraction provider chain failed", error)
            return _manual("proveedor")
        if respuesta.tokens_entrada is None or respuesta.tokens_salida is None:
            coste = reserva.estimado_eur
        else:
            primario = respuesta.modelo == modelo
            coste = extraccion.coste_real_eur(respuesta.tokens_entrada, respuesta.tokens_salida, primario=primario)
        extraccion.marcar_completada(reserva.id, coste, respuesta.tokens_entrada, respuesta.tokens_salida)
        cerrada = True
        encontradas = propuestas.validar(respuesta.contenido, texto)
    finally:
        if not cerrada:
            extraccion.marcar_fallida(reserva.id)
    if not encontradas:
        return _manual("indisponible")
    return {"estado": "propuesta", "propuestas": encontradas}

