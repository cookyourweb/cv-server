"""Autenticacion con Google: verificar el token y comprobar la lista de invitadas.

Logica pura, sin depender de ningun framework web: la reutiliza cualquier servidor. Nada se lee del entorno al
importar; la configuracion se pide con `ConfiguracionOIDC.desde_entorno()`.
"""
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
