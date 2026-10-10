"""AES-256-GCM encryption for stored CV masters (ADR-007).

Row stored per master: (clave_version, nonce 12 bytes, cifrado). The AAD binds
each ciphertext to its owner and language, so rows cannot be swapped between
users or languages. Keys live in the environment, never in the database:

    CV_CLAVES="1:<base64 32 bytes>,2:<base64 32 bytes>"
    CV_CLAVE_ACTIVA="2"

Any configuration or decryption problem raises ErrorDeCifrado (fail closed).
Messages are generic on purpose: they never carry content, ids or key material.
"""
import base64
import binascii
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

LARGO_CLAVE = 32
LARGO_NONCE = 12


class ErrorDeCifrado(Exception):
    """Encryption is unusable or the data does not authenticate."""


def _llavero() -> dict:
    bruto = os.environ.get("CV_CLAVES", "")
    llavero = {}
    for par in filter(None, (p.strip() for p in bruto.split(","))):
        version, sep, valor = par.partition(":")
        try:
            clave = base64.b64decode(valor, validate=True)
            numero = int(version)
        except (ValueError, binascii.Error):
            raise ErrorDeCifrado("Invalid key configuration") from None
        # A repeated version would silently shadow another key: refuse it.
        if not sep or len(clave) != LARGO_CLAVE or numero in llavero:
            raise ErrorDeCifrado("Invalid key configuration")
        llavero[numero] = clave
    if not llavero:
        raise ErrorDeCifrado("No encryption keys configured")
    return llavero


def _version_activa(llavero: dict) -> int:
    try:
        activa = int(os.environ.get("CV_CLAVE_ACTIVA", ""))
    except ValueError:
        raise ErrorDeCifrado("No active key configured") from None
    if activa not in llavero:
        raise ErrorDeCifrado("The active key is not in the keyring")
    return activa


def _aad(usuario_id, idioma) -> bytes:
    # Fail closed: an empty or mistyped owner would bind data to a meaningless AAD.
    if isinstance(usuario_id, uuid.UUID):
        usuario_id = str(usuario_id)
    if not isinstance(usuario_id, str) or not usuario_id.strip():
        raise ErrorDeCifrado("Invalid user identifier")
    return f"cv_master:{usuario_id}:{idioma}".encode("utf-8")


def cifrar(texto: str, usuario_id, idioma: str) -> tuple:
    """Encrypt with the active key. Returns (clave_version, nonce, cifrado)."""
    llavero = _llavero()
    version = _version_activa(llavero)
    nonce = os.urandom(LARGO_NONCE)
    cifrado = AESGCM(llavero[version]).encrypt(
        nonce, texto.encode("utf-8"), _aad(usuario_id, idioma))
    return version, nonce, cifrado


def descifrar(clave_version: int, nonce: bytes, cifrado: bytes, usuario_id, idioma: str) -> str:
    """Decrypt with the key version stored in the row."""
    llavero = _llavero()
    if clave_version not in llavero:
        raise ErrorDeCifrado("Unknown key version")
    if len(nonce) != LARGO_NONCE:
        raise ErrorDeCifrado("Decryption failed")
    try:
        plano = AESGCM(llavero[clave_version]).decrypt(
            bytes(nonce), bytes(cifrado), _aad(usuario_id, idioma))
    except InvalidTag:
        raise ErrorDeCifrado("Decryption failed") from None
    return plano.decode("utf-8")


def recifrar(clave_version: int, nonce: bytes, cifrado: bytes, usuario_id, idioma: str) -> tuple:
    """Re-encrypt a row with the active key (rotation)."""
    return cifrar(descifrar(clave_version, nonce, cifrado, usuario_id, idioma), usuario_id, idioma)
