"""Database access: SQLAlchemy Core on Neon Postgres through psycopg 3.

The engine is built lazily, on first use, from DATABASE_URL. Importing this module
never reads the environment and never opens a connection, so the service can start
(and /health can answer) while the database is cold or unreachable.

The pool is deliberately tiny: Neon's pooled endpoint (PgBouncer) multiplexes the
real connections, and the free plan caps them. `pool_pre_ping` and `pool_recycle`
absorb connections that Neon drops when a compute scales to zero.

Errors are generic on purpose: they never include the connection string.
"""
import os
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import create_engine

_PREFIJO_PSYCOPG = "postgresql+psycopg://"
_PREFIJOS_ADMITIDOS = ("postgresql+psycopg://", "postgresql://", "postgres://")

_motor = None


class ErrorDeBaseDeDatos(Exception):
    """The database is not configured correctly."""


def url_psycopg(url: str) -> str:
    """Normalise a Postgres URL so SQLAlchemy selects the psycopg 3 driver."""
    for prefijo in _PREFIJOS_ADMITIDOS:
        if url.startswith(prefijo):
            return _PREFIJO_PSYCOPG + url[len(prefijo):]
    raise ErrorDeBaseDeDatos("DATABASE_URL must be a PostgreSQL URL")


def crear_motor(url: str):
    """Build an engine for `url`. Lazy: no connection is opened here."""
    destino = url_psycopg(url)
    # Enforce TLS unless the URL states its own sslmode (e.g. verify-full).
    argumentos = {} if "sslmode" in parse_qs(urlsplit(destino).query) else {"sslmode": "require"}
    return create_engine(
        destino,
        connect_args=argumentos,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=300,
    )


def motor():
    """Return the process-wide engine, creating it on first use."""
    global _motor
    if _motor is None:
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise ErrorDeBaseDeDatos("DATABASE_URL is not set")
        _motor = crear_motor(url)
    return _motor


def cerrar() -> None:
    """Dispose of the shared engine (used on shutdown and between tests)."""
    global _motor
    if _motor is not None:
        _motor.dispose()
        _motor = None


@contextmanager
def transaccion():
    """Yield a connection inside a transaction: commit on success, roll back on error."""
    with motor().begin() as conexion:
        yield conexion
