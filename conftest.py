"""Config de tests.

Ya no hace falta inyectar credenciales: desde el 28-ago-2026 los modulos se
importan sin ninguna variable de entorno. La validacion vive en `server.py` y
reporta las que faltan al arrancar, no al importar.

Ver `tests/test_modulos_sin_entorno.py`, que lo comprueba en un proceso limpio.
"""

import os
from pathlib import Path

import pytest


def _url_de_pruebas() -> str:
    """Test database URL: the environment first, then a local `.env` (never printed)."""
    url = os.getenv("DATABASE_URL_PRUEBAS", "")
    if not url and (Path(__file__).parent / ".env").exists():
        from dotenv import dotenv_values

        url = dotenv_values(Path(__file__).parent / ".env").get("DATABASE_URL_PRUEBAS") or ""
    return url


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "bd: needs a real PostgreSQL (DATABASE_URL_PRUEBAS); skipped when it is unset"
    )


def pytest_collection_modifyitems(config, items):
    if _url_de_pruebas():
        return
    omitir = pytest.mark.skip(reason="DATABASE_URL_PRUEBAS is not set")
    for item in items:
        if "bd" in item.keywords:
            item.add_marker(omitir)


@pytest.fixture(scope="session")
def url_de_pruebas() -> str:
    return _url_de_pruebas()
