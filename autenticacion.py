"""Autenticacion con Google: verificar el token y comprobar la lista de invitadas.

Logica pura, sin depender de ningun framework web: la reutiliza cualquier servidor. Nada se lee del entorno al
importar; la configuracion se pide con `ConfiguracionOIDC.desde_entorno()`.
"""
import os
from dataclasses import dataclass


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
