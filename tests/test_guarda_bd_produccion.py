"""Database tests must never run against the service (production) database.

On 18-oct-2026 a local .env had DATABASE_URL_PRUEBAS equal to DATABASE_URL, so every
`bd` test (migrations included) ran against production. The session must abort before
any connection when both point at the same server and database, whatever the password
or query string says.
"""
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CON_BD = "tests/test_vectores.py"            # has pure tests and `bd` tests
SIN_BD = "tests/test_encaje_semantico.py"    # pure module, no `bd` tests

PROD = "postgresql://owner:secret@db.example.test:5432/neondb?sslmode=require"


def _pytest(objetivo, extra_env, *args):
    entorno = {k: v for k, v in os.environ.items()
               if k not in ("ALLOW_DESTRUCTIVE_DB_TESTS", "DATABASE_URL", "DATABASE_URL_PRUEBAS")}
    entorno.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", objetivo, *args],
        cwd=RAIZ, env=entorno, capture_output=True, text=True, timeout=120,
    )


def test_aborts_when_the_test_database_is_the_service_database():
    r = _pytest(CON_BD, {"DATABASE_URL": PROD, "DATABASE_URL_PRUEBAS": PROD})
    assert r.returncode != 0
    assert "same database as DATABASE_URL" in r.stdout + r.stderr


def test_aborts_even_if_password_or_query_differ():
    otra = "postgresql://owner:other@db.example.test/neondb?channel_binding=require"
    r = _pytest(CON_BD, {"DATABASE_URL": PROD, "DATABASE_URL_PRUEBAS": otra})
    assert r.returncode != 0
    assert "same database as DATABASE_URL" in r.stdout + r.stderr


def test_the_password_never_reaches_the_output():
    r = _pytest(CON_BD, {"DATABASE_URL": PROD, "DATABASE_URL_PRUEBAS": PROD})
    assert "secret" not in r.stdout + r.stderr


def test_non_database_tests_still_run_with_the_same_url():
    r = _pytest(SIN_BD, {"DATABASE_URL": PROD, "DATABASE_URL_PRUEBAS": PROD})
    assert r.returncode == 0, r.stdout + r.stderr


def test_deselecting_database_tests_lets_the_rest_run():
    r = _pytest(CON_BD, {"DATABASE_URL": PROD, "DATABASE_URL_PRUEBAS": PROD}, "-m", "not bd")
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_different_database_is_not_blocked():
    pruebas = "postgresql://owner:secret@db.example.test:5432/neondb_pruebas"
    r = _pytest(CON_BD, {"DATABASE_URL": PROD, "DATABASE_URL_PRUEBAS": pruebas}, "-m", "not bd")
    assert "same database as DATABASE_URL" not in r.stdout + r.stderr
