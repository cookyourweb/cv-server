"""Config de tests.

Ya no hace falta inyectar credenciales: desde el 28-ago-2026 los modulos se
importan sin ninguna variable de entorno. La validacion vive en `server.py` y
reporta las que faltan al arrancar, no al importar.

Ver `tests/test_modulos_sin_entorno.py`, que lo comprueba en un proceso limpio.
"""

import os
from pathlib import Path

import pytest


def _url_del_entorno(nombre: str) -> str:
    """A database URL: the environment first, then a local `.env` (never printed)."""
    url = os.getenv(nombre, "")
    if not url and (Path(__file__).parent / ".env").exists():
        from dotenv import dotenv_values

        url = dotenv_values(Path(__file__).parent / ".env").get(nombre) or ""
    return url


def _url_de_pruebas() -> str:
    return _url_del_entorno("DATABASE_URL_PRUEBAS")


def _destino(url: str) -> tuple:
    """Server and database a URL points at; credentials and query string do not count."""
    from urllib.parse import urlparse

    partes = urlparse(url)
    return ((partes.hostname or "").lower(), partes.port or 5432, partes.path.lstrip("/"))


def pytest_collection_finish(session):
    """Abort before any connection if a selected `bd` test would hit the service database.

    On 18-oct-2026 a local .env had DATABASE_URL_PRUEBAS equal to DATABASE_URL and every
    `bd` test ran against production. Runs after deselection, so `-m "not bd"` still works.
    """
    pruebas, servicio = _url_de_pruebas(), _url_del_entorno("DATABASE_URL")
    if not pruebas or not servicio or _destino(pruebas) != _destino(servicio):
        return
    if any("bd" in item.keywords for item in session.items):
        pytest.exit(
            "DATABASE_URL_PRUEBAS points at the same database as DATABASE_URL (the service "
            "database). Point it at a disposable database, such as a Neon branch, or run "
            'with -m "not bd".',
            returncode=3,
        )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "bd: needs a real PostgreSQL (DATABASE_URL_PRUEBAS); skipped when it is unset"
    )
    config.addinivalue_line(
        "markers",
        "bd_destructiva: drops schema objects (alembic downgrade base); "
        "skipped unless ALLOW_DESTRUCTIVE_DB_TESTS=1 is set in the environment",
    )


def pytest_collection_modifyitems(config, items):
    if not _url_de_pruebas():
        omitir = pytest.mark.skip(reason="DATABASE_URL_PRUEBAS is not set")
        for item in items:
            if "bd" in item.keywords:
                item.add_marker(omitir)
    if os.getenv("ALLOW_DESTRUCTIVE_DB_TESTS") != "1":
        omitir = pytest.mark.skip(
            reason="destructive DB test: set ALLOW_DESTRUCTIVE_DB_TESTS=1 (and point "
            "DATABASE_URL_PRUEBAS at a disposable database) to run it"
        )
        for item in items:
            if "bd_destructiva" in item.keywords:
                item.add_marker(omitir)


@pytest.fixture(scope="session")
def url_de_pruebas() -> str:
    return _url_de_pruebas()


@pytest.fixture(autouse=True)
def _sin_base_de_datos_de_servicio(monkeypatch):
    """No test may reach the service database by accident: the legacy (no database)
    mode is the default, and a test that wants a database sets DATABASE_URL itself."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
