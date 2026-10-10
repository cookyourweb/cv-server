"""Destructive database tests (`downgrade base`) need an explicit opt-in.

Without ALLOW_DESTRUCTIVE_DB_TESTS=1 they must be skipped, even when a test
database URL is configured: a wrong URL must never cost anyone a schema.
"""
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTRUCTIVO = "tests/test_migracion_0001.py::test_upgrade_downgrade_upgrade_is_clean"


def _pytest(extra_env):
    entorno = {k: v for k, v in os.environ.items() if k != "ALLOW_DESTRUCTIVE_DB_TESTS"}
    entorno.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", DESTRUCTIVO],
        cwd=RAIZ, env=entorno, capture_output=True, text=True, timeout=120,
    )


def test_destructive_test_is_skipped_without_opt_in():
    r = _pytest({})
    assert "1 skipped" in r.stdout, r.stdout
    assert "ALLOW_DESTRUCTIVE_DB_TESTS" in r.stdout


def test_destructive_test_is_skipped_when_opt_in_is_not_exactly_one():
    r = _pytest({"ALLOW_DESTRUCTIVE_DB_TESTS": "0"})
    assert "1 skipped" in r.stdout, r.stdout
