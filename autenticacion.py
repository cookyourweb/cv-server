"""Autenticacion con Google: verificar el token y comprobar la lista de invitadas.

Logica pura, sin depender de ningun framework web: la reutiliza cualquier
servidor. Nada se lee del entorno al importar; la configuracion se pide con
`ConfiguracionOIDC.desde_entorno()`.
"""
import base64
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import rsa
from google.auth import jwt


class ErrorDeAutenticacion(Exception):
    """Token ausente, mal formado o no verificable. El servidor responde 401."""


class NoInvitada(Exception):
    """Identidad valida pero fuera de la lista. El servidor responde 403.

    A proposito NO hereda de ErrorDeAutenticacion: un `except ErrorDeAutenticacion`
    no puede convertir un 403 en un 401.
    """


class ProveedorNoDisponible(Exception):
    """No hay configuracion completa o no se pueden obtener las claves. 503."""


@dataclass(frozen=True)
class Identidad:
    emisor: str
    sub: str
    email: str
    nombre: str


def _lista(texto: str) -> list[str]:
    return [p.strip() for p in (texto or "").split(",") if p.strip()]


@dataclass(frozen=True)
class ConfiguracionOIDC:
    audiencia: str
    emisores: tuple[str, ...]
    url_jwks: str
    invitadas: frozenset[str]

    @classmethod
    def desde_entorno(cls, entorno=None) -> "ConfiguracionOIDC":
        """Lee la configuracion al llamar, nunca al importar."""
        e = os.environ if entorno is None else entorno
        return cls(
            audiencia=(e.get("OIDC_AUDIENCIA") or "").strip(),
            emisores=tuple(_lista(e.get("OIDC_EMISORES"))),
            url_jwks=(e.get("OIDC_URL_JWKS") or "").strip(),
            invitadas=frozenset(p.lower() for p in _lista(e.get("OIDC_INVITADAS"))),
        )

    def completa(self) -> bool:
        return bool(self.audiencia and self.emisores and self.url_jwks)


ALGORITMOS = ("RS256",)  # lista cerrada: el alg del token nunca elige el verificador
MARGEN_RELOJ = 60  # segundos de tolerancia en exp e iat
REFRESCO_MINIMO = 300  # segundos entre descargas provocadas por un kid desconocido


def _descargar_jwks(url: str) -> dict:
    import requests

    respuesta = requests.get(url, timeout=5)
    respuesta.raise_for_status()
    return respuesta.json()


def _entero(b64url: str) -> int:
    relleno = "=" * (-len(b64url) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(b64url + relleno), "big")


def _pem_de_jwk(jwk: dict) -> str:
    return rsa.PublicKey(_entero(jwk["n"]), _entero(jwk["e"])).save_pkcs1().decode()


class ClavesPublicas:
    """Cache kid -> PEM de las claves del proveedor, con TTL y refresco acotado."""

    def __init__(self, url: str, descargar: Callable[[str], dict] | None = None,
                 ttl: int = 3600, reloj: Callable[[], float] = time.monotonic):
        self._url = url
        self._descargar = descargar or _descargar_jwks
        self._ttl = ttl
        self._reloj = reloj
        self._pems: dict[str, str] = {}
        self._cargadas_en: float | None = None
        self._ultimo_intento: float | None = None
        self._cerrojo = threading.Lock()

    def _refrescar(self) -> None:
        self._ultimo_intento = self._reloj()
        try:
            claves = self._descargar(self._url)["keys"]
            nuevas = {k["kid"]: _pem_de_jwk(k) for k in claves if k.get("kty") == "RSA"}
        except Exception as error:
            if not self._pems:
                raise ProveedorNoDisponible("no se pudieron obtener las claves publicas") from error
            return  # hay cache: se sigue sirviendo
        if not nuevas and not self._pems:
            raise ProveedorNoDisponible("el proveedor no publico ninguna clave RSA")
        if nuevas:
            self._pems = nuevas
            self._cargadas_en = self._reloj()

    def _puede_reintentar(self, ahora: float) -> bool:
        return self._ultimo_intento is None or ahora - self._ultimo_intento >= REFRESCO_MINIMO

    def pem_de(self, kid: str) -> str | None:
        # El cerrojo cubre tambien la descarga: 8 peticiones a la vez, 1 sola descarga.
        with self._cerrojo:
            ahora = self._reloj()
            if self._cargadas_en is None:
                self._refrescar()
            elif ahora - self._cargadas_en >= self._ttl and self._puede_reintentar(ahora):
                self._refrescar()
            if kid not in self._pems and self._puede_reintentar(ahora):
                self._refrescar()
            return self._pems.get(kid)


def verificar_token(token: str, config: ConfiguracionOIDC, claves: ClavesPublicas) -> Identidad:
    """Comprueba firma, audiencia, caducidad, emisor y email verificado."""
    try:
        cabecera = jwt.decode_header(token)
        kid = cabecera.get("kid")
        if cabecera.get("alg") not in ALGORITMOS or not isinstance(kid, str):
            raise ErrorDeAutenticacion("algoritmo o kid no admitidos")
    except ValueError as error:
        raise ErrorDeAutenticacion("token mal formado") from error

    pem = claves.pem_de(kid)  # ProveedorNoDisponible sube tal cual
    if pem is None:
        raise ErrorDeAutenticacion("kid desconocido")

    try:
        datos = jwt.decode(token, certs=pem, audience=config.audiencia,
                           clock_skew_in_seconds=MARGEN_RELOJ)
    except Exception as error:
        raise ErrorDeAutenticacion("token no verificable") from error

    if datos.get("iss") not in config.emisores:
        raise ErrorDeAutenticacion("emisor no admitido")
    if datos.get("email_verified") is not True:
        raise ErrorDeAutenticacion("email sin verificar")
    email = datos.get("email")
    if not isinstance(email, str) or not email:
        raise ErrorDeAutenticacion("el token no trae email")
    return Identidad(datos["iss"], str(datos.get("sub", "")), email, str(datos.get("name") or ""))
