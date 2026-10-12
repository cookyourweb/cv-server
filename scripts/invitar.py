"""Add (or renew) an invitation so a person can sign in with their Google account.

Usage:
    python scripts/invitar.py ana@example.com --dias 14

DATABASE_URL must be set in the environment. The script never prints it. An unused
invitation is renewed; one that was already used is refused (the person has an account).
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

import base_de_datos  # noqa: E402

_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErrorDeInvitacion(Exception):
    """The invitation cannot be created; the message is safe to print."""


def invitar(email: str, dias: int, conexion) -> str:
    """Insert or renew the invitation for `email`; return the stored (lower-case) address."""
    correo = (email or "").strip().lower()
    if not _CORREO.match(correo):
        raise ErrorDeInvitacion("the email address is not valid")
    if not 1 <= dias <= 365:
        raise ErrorDeInvitacion("--dias must be between 1 and 365")
    fila = conexion.execute(text(
        "INSERT INTO invitaciones (email, caduca_en) VALUES (:e, now() + make_interval(days => :d)) "
        "ON CONFLICT (email) DO UPDATE SET caduca_en = EXCLUDED.caduca_en WHERE invitaciones.usada_en IS NULL "
        "RETURNING email"), {"e": correo, "d": dias}).first()
    if fila is None:
        raise ErrorDeInvitacion("that invitation was already used")
    return correo


def _guardar(email: str, dias: int) -> str:
    with base_de_datos.transaccion() as conexion:
        return invitar(email, dias, conexion)


def main(argv=None) -> int:
    analizador = argparse.ArgumentParser(description="Invite an email address to sign in.")
    analizador.add_argument("email")
    analizador.add_argument("--dias", type=int, required=True, help="days until the invitation expires (1-365)")
    args = analizador.parse_args(argv)
    if not base_de_datos.configurada():
        print("error: set DATABASE_URL in the environment", file=sys.stderr)
        return 1
    try:
        correo = _guardar(args.email, args.dias)
    except ErrorDeInvitacion as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        print(f"error: database unavailable ({type(error).__name__})", file=sys.stderr)
        return 1
    print(f"invited {correo} for {args.dias} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
