"""Almacenamiento cifrado de la API key de la usuaria para BYOK."""

import base64
import binascii
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

LARGO_CLAVE = 32
LARGO_NONCE = 12


class ErrorDeCifrado(Exception):
    """Encryption/decryption failures; messages are generic by design."""


def _llavero():
    bruto = os.environ.get("BYOK_CLAVES", os.environ.get("CV_CLAVES", ""))
    llavero = {}
    for par in filter(None, (p.strip() for p in bruto.split(","))):
        version, sep, valor = par.partition(":")
        try:
            clave = base64.b64decode(valor, validate=True)
            numero = int(version)
        except (ValueError, binascii.Error):
            raise ErrorDeCifrado("Invalid key configuration") from None
        if not sep or len(clave) != LARGO_CLAVE or numero in llavero:
            raise ErrorDeCifrado("Invalid key configuration")
        llavero[numero] = clave
    if not llavero:
        raise ErrorDeCifrado("No encryption keys configured")
    return llavero


def _version_activa(llavero):
    try:
        activa = int(os.environ.get("BYOK_CLAVE_ACTIVA", os.environ.get("CV_CLAVE_ACTIVA", "")))
    except ValueError:
        raise ErrorDeCifrado("No active key configured") from None
    if activa not in llavero:
        raise ErrorDeCifrado("The active key is not in the keyring")
    return activa


def _aad(usuario_id, proveedor):
    if isinstance(usuario_id, uuid.UUID):
        usuario_id = str(usuario_id)
    if not isinstance(usuario_id, str) or not usuario_id.strip():
        raise ErrorDeCifrado("Invalid user identifier")
    if proveedor not in {"anthropic", "groq"}:
        raise ErrorDeCifrado("Invalid provider")
    return f"byok:{usuario_id}:{proveedor}".encode("utf-8")


def cifrar_api_key(usuario_id, proveedor: str, api_key: str) -> tuple:
    if not isinstance(api_key, str) or not api_key.strip():
        raise ErrorDeCifrado("API key is empty")
    llavero = _llavero()
    version = _version_activa(llavero)
    nonce = os.urandom(LARGO_NONCE)
    cifrado = AESGCM(llavero[version]).encrypt(
        nonce, api_key.encode("utf-8"), _aad(usuario_id, proveedor))
    return version, nonce, cifrado


def descifrar_api_key(usuario_id, proveedor: str, clave_version: int, nonce, cifrado) -> str:
    llavero = _llavero()
    if clave_version not in llavero:
        raise ErrorDeCifrado("Unknown key version")
    if len(nonce) != LARGO_NONCE:
        raise ErrorDeCifrado("Decryption failed")
    try:
        plano = AESGCM(llavero[clave_version]).decrypt(bytes(nonce), bytes(cifrado),
                                                      _aad(usuario_id, proveedor))
    except InvalidTag:
        raise ErrorDeCifrado("Decryption failed") from None
    return plano.decode("utf-8")


def validar_api_key(proveedor: str, api_key: str) -> bool:
    if not api_key or not api_key.strip():
        return False
    if proveedor == "anthropic":
        return api_key.startswith("sk-ant-")
    if proveedor == "groq":
        return api_key.startswith("gsk_")
    return False

def resolver_generacion(repo, proveedor: str = "anthropic") -> dict:
    """Decide si una usuaria puede generar, y con qué fuente de clave.

    Modos posibles:
    - "key": usa su propia clave.
    - "trial": usa una de las 3 generaciones gratuitas.
    - "denegado": no puede generar.

    Cuando devuelve "trial", el caller debe usar la clave del sistema solo si esa
    via trial está habilitada por configuración. La reserva del trial se hace
    antes de la llamada al modelo, así que si la generación falla, el consumo
    no se revierte en esta V1.
    """
    if repo.tiene_clave_api(proveedor):
        try:
            clave = repo.obtener_clave_api(proveedor)
            return {
                "permitido": True,
                "modo": "key",
                "clave": clave,
                "motivo": None,
            }
        except ErrorDeCifrado:
            return {
                "permitido": False,
                "modo": "denegado",
                "clave": None,
                "motivo": "La clave guardada ya no es válida.",
            }

    if getattr(repo, "consumir_trial", lambda: False)():
        return {
            "permitido": True,
            "modo": "trial",
            "clave": None,
            "motivo": "Modo demo: una generación gratuita consumida.",
        }

    return {
        "permitido": False,
        "modo": "denegado",
        "clave": None,
        "motivo": "Te quedan 0 generaciones de prueba. Añade tu propia clave para seguir.",
    }


def _denegado(motivo: str) -> dict:
    return {"permitido": False, "modo": "denegado", "clave": None, "motivo": motivo}


def _es_propietaria(email: str) -> bool:
    # BYOK_PROPIETARIAS: comma-separated owner emails that always generate with the
    # server key. Only machine-key routes reach the gate, so this is not a public bypass.
    import os
    lista = {e.strip().lower() for e in os.environ.get("BYOK_PROPIETARIAS", "").split(",") if e.strip()}
    return bool(email) and email.strip().lower() in lista


def resolver_generacion_por_email(email: str, conexion, proveedor: str = "anthropic") -> dict:
    """Resolve a BYOK decision from an email. Fails closed: any doubt means denied."""
    if _es_propietaria(email):
        return {"permitido": True, "modo": "propietaria", "clave": None, "motivo": None}
    if not email or conexion is None:
        return _denegado("No se pudo verificar tu cuenta; inténtalo más tarde.")

    try:
        from usuarias import id_por_emails
        from repositorio import RepositorioDeUsuaria
    except ImportError:
        return _denegado("Servicio de claves no disponible.")

    try:
        usuario_id = id_por_emails([email], conexion)
    except Exception:
        return _denegado("No se pudo verificar tu cuenta; inténtalo más tarde.")

    if not usuario_id:
        return _denegado("Cuenta no registrada: crea tu cuenta y añade tu clave para generar.")

    repo = RepositorioDeUsuaria(conexion, usuario_id)
    return resolver_generacion(repo, proveedor)


import hashlib
import logging

logger = logging.getLogger("byok")


def registrar_modo_generacion(modo: str, motivo: str | None = None, proveedor: str = "anthropic",
                              usuario_hint: str | None = None) -> None:
    """Log de auditoría sin secretos ni contenido del CV."""
    hint = usuario_hint or "desconocido"
    if hint not in ("desconocido", "legacy", "trial"):
        hint = hashlib.sha256(hint.encode("utf-8")).hexdigest()[:12]
    logger.info("byok-audit provider=%s mode=%s reason=%s user=%s", proveedor, modo, motivo or "ok", hint)
