"""Users and invitations: map a verified Google identity to an internal user id.

The identity is the pair (issuer, subject), never the email: a mailbox is only the
key of an invitation and a label stored in `usuario_emails`. A user may own several
mailboxes, but a mailbox belongs to exactly one user.

Rules (spec REQ-1.1 to REQ-1.3):
- A known (issuer, subject) signs in. A new mailbox for it is attached only when an
  unused, unexpired invitation exists for that mailbox.
- An unknown (issuer, subject) needs such an invitation. It creates the user, stores
  the mailbox as primary and consumes the invitation, all in one transaction.
- A mailbox already held by another user is never merged: access is denied.
- Denial writes nothing.

Nothing here reads the environment at import time or opens a connection until a
function is called.
"""
import logging
import uuid
from functools import wraps

from flask import g, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import base_de_datos
from autenticacion import ErrorDeAutenticacion, Identidad, NoInvitada, ProveedorNoDisponible

logger = logging.getLogger(__name__)


class BaseDeDatosNoDisponible(Exception):
    """The database could not be reached or answered with an error.

    Carries no detail on purpose: driver messages may contain the connection string.
    """


def _normalizar(email: str) -> str:
    return email.strip().lower()


def _invitacion_vigente(c, email: str) -> bool:
    """Lock and report the invitation for `email` if it is unused and not expired."""
    return c.execute(text(
        "SELECT 1 FROM invitaciones WHERE email = :e AND usada_en IS NULL AND caduca_en > now() "
        "FOR UPDATE"), {"e": email}).first() is not None


def _consumir(c, email: str, usuario_id) -> None:
    c.execute(text("UPDATE invitaciones SET usada_en = now(), usada_por = :u WHERE email = :e"),
              {"e": email, "u": usuario_id})


def _resolver(c, identidad: Identidad, respaldo: frozenset):
    email = _normalizar(identidad.email)
    conocida = c.execute(
        text("SELECT id FROM usuarios WHERE emisor = :i AND sub = :s"),
        {"i": identidad.emisor, "s": identidad.sub}).scalar_one_or_none()

    titular = c.execute(
        text("SELECT usuario_id FROM usuario_emails WHERE email = :e"), {"e": email}).scalar_one_or_none()
    if titular is not None:
        # The mailbox exists: it is this user's, or it is someone else's and stays theirs.
        return conocida if conocida == titular else None

    invitada = _invitacion_vigente(c, email)
    if conocida is not None:
        if invitada:  # a second mailbox of an account we already know
            c.execute(text("INSERT INTO usuario_emails (email, usuario_id, principal) VALUES (:e, :u, false)"),
                      {"e": email, "u": conocida})
            _consumir(c, email, conocida)
        return conocida  # the subject identifies her; an unknown mailbox just stays unlinked

    if not invitada and email not in respaldo:
        return None
    nuevo = c.execute(
        text("INSERT INTO usuarios (emisor, sub, nombre) VALUES (:i, :s, :n) RETURNING id"),
        {"i": identidad.emisor, "s": identidad.sub, "n": identidad.nombre or None}).scalar_one()
    c.execute(text("INSERT INTO usuario_emails (email, usuario_id, principal) VALUES (:e, :u, true)"),
              {"e": email, "u": nuevo})
    if invitada:
        _consumir(c, email, nuevo)
    return nuevo


def resolver_o_crear(identidad: Identidad, conexion=None, respaldo: frozenset = frozenset()):
    """Return the user id for a verified identity, or None when access is denied.

    `respaldo` is the bootstrap allowlist (lower-case emails) that may sign in without
    an invitation row; empty by default. Pass `conexion` to run inside an existing
    transaction (tests); otherwise one is opened and committed here.
    """
    try:
        if conexion is not None:
            with conexion.begin_nested():
                return _resolver(conexion, identidad, respaldo)
        with base_de_datos.transaccion() as nueva:
            return _resolver(nueva, identidad, respaldo)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        logger.error("database error resolving a user: %s", type(error).__name__)
        raise BaseDeDatosNoDisponible() from None


def _existe(consulta: str, usuario_id, conexion) -> bool:
    try:
        if conexion is not None:
            return conexion.execute(text(consulta), {"u": usuario_id}).first() is not None
        with base_de_datos.transaccion() as nueva:
            return nueva.execute(text(consulta), {"u": usuario_id}).first() is not None
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        logger.error("database error reading a profile: %s", type(error).__name__)
        raise BaseDeDatosNoDisponible() from None


def tiene_perfil(usuario_id, conexion=None) -> bool:
    return _existe("SELECT 1 FROM perfil WHERE usuario_id = :u", usuario_id, conexion)


def tiene_master(usuario_id, conexion=None) -> bool:
    return _existe("SELECT 1 FROM cv_master WHERE usuario_id = :u", usuario_id, conexion)


def crear_con_usuaria(autenticar):
    """Build the `@con_usuaria` decorator around a request authenticator.

    `autenticar()` returns `(identidad, usuario_id)` or raises the errors of
    autenticacion.py. The decorator answers 401, 403 or 503 with generic bodies and,
    on success, sets `g.identidad` and `g.usuario_id` for owner-scoped routes.
    `usuario_id` is None only in the legacy mode where no database is configured.
    """
    def con_usuaria(vista):
        @wraps(vista)
        def envuelta(*args, **kwargs):
            try:
                g.identidad, g.usuario_id = autenticar()
            except ErrorDeAutenticacion:
                return jsonify({"ok": False, "error": "no autenticada"}), 401
            except NoInvitada:
                return jsonify({"ok": False, "error": "acceso no permitido"}), 403
            except (ProveedorNoDisponible, BaseDeDatosNoDisponible):
                return jsonify({"ok": False, "error": "servicio no disponible"}), 503
            return vista(*args, **kwargs)
        return envuelta
    return con_usuaria


__all__ = ["BaseDeDatosNoDisponible", "crear_con_usuaria", "resolver_o_crear",
           "tiene_master", "tiene_perfil", "uuid"]
