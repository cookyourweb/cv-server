"""The external backup workflow (ADR-008) keeps its safety properties.

The workflow cannot run in the test suite, so these tests read the YAML as text and pin
the properties that must not drift: it runs daily and on demand, it dumps with a client
that matches the server major version, the dump is encrypted before it touches disk, only
the encrypted file is uploaded, and no secret is ever printed.

Text checks instead of a YAML parser: PyYAML is not a dependency of this project.
"""
import re
from pathlib import Path

import pytest

RUTA = Path(__file__).parent.parent / ".github" / "workflows" / "neon-backup.yml"
SECRETOS = ("NEON_BACKUP_URL", "AGE_PUBLIC_KEY")


@pytest.fixture(scope="module")
def texto() -> str:
    assert RUTA.exists(), f"{RUTA.name} is missing"
    return RUTA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def lineas(texto) -> list:
    return [linea.rstrip() for linea in texto.splitlines()]


def test_it_runs_on_a_daily_schedule_and_on_demand(texto):
    assert re.search(r"^on:\s*$", texto, re.M)
    assert re.search(r"^\s+schedule:\s*$", texto, re.M)
    assert re.search(r'^\s+- cron: "[^"]+"\s*$', texto, re.M)
    cron = re.search(r'cron: "([^"]+)"', texto).group(1).split()
    assert len(cron) == 5 and cron[2:] == ["*", "*", "*"], "the cron must fire once a day"
    assert re.search(r"^\s+workflow_dispatch:", texto, re.M)


@pytest.mark.parametrize("secreto", SECRETOS)
def test_each_secret_is_read_from_the_secrets_context(texto, secreto):
    assert "${{ secrets.%s }}" % secreto in texto


@pytest.mark.parametrize("secreto", SECRETOS)
def test_a_secret_is_only_bound_to_an_environment_variable(lineas, secreto):
    # Never interpolated inside a command: that would put it in the shell script text.
    for linea in lineas:
        if f"secrets.{secreto}" in linea:
            assert re.fullmatch(rf"\s+{secreto}: \$\{{\{{ secrets\.{secreto} \}}\}}", linea), linea


def test_no_command_prints_a_secret_or_traces_the_shell(lineas):
    for linea in lineas:
        ejecutable = linea.split("#", 1)[0]
        assert "set -x" not in ejecutable and "bash -x" not in ejecutable, linea
        if re.search(r"\becho\b|\bprintf\b|\benv\b|\bprintenv\b|\bcat\b", ejecutable):
            assert not any(re.search(rf"\$\{{?{s}\b", ejecutable) for s in SECRETOS), linea


def test_it_fails_clearly_when_a_secret_is_missing(texto):
    # The check loops over both names and reads each value by indirection.
    assert re.search(r'\[ -z "\$\{!\w+\}" \]', texto)
    assert "::error::" in texto and "exit 1" in texto
    comprobacion = texto.index("-z")
    assert comprobacion < texto.index("pg_dump"), "secrets are checked before the dump"


def test_the_dump_client_matches_postgres_18(texto):
    assert re.search(r"postgres:18\b", texto)
    assert "pg_dump" in texto


def test_the_dump_is_encrypted_before_it_is_written(texto):
    # pg_dump streams to age: the plain dump never exists as a file.
    junto = re.sub(r"\\\n\s*", " ", texto)
    assert re.search(r"pg_dump[^\n]*\|\s*age\b", junto)
    assert not re.search(r"pg_dump[^\n]*(--file|\s-f\s)", junto)
    assert re.search(r'\bage\b[^\n]*-r "\$AGE_PUBLIC_KEY"', junto)


def test_only_the_encrypted_file_is_uploaded(lineas):
    rutas = [linea for linea in lineas if re.match(r"\s+path:\s", linea)]
    assert len(rutas) == 1
    destino = rutas[0].split("path:", 1)[1].strip()
    assert destino.startswith("backup/") and destino.endswith(".dump.age")


def test_the_artifact_is_kept_thirty_days_and_a_missing_file_fails_the_run(texto):
    assert re.search(r"^\s+retention-days: 30\s*$", texto, re.M)
    assert re.search(r"^\s+if-no-files-found: error\s*$", texto, re.M)


def test_the_job_has_least_privilege_and_a_timeout(texto):
    assert re.search(r"^permissions:\s*\n\s+contents: read\s*$", texto, re.M)
    assert re.search(r"^\s+timeout-minutes: \d+\s*$", texto, re.M)
