"""infra/secrets/entorno.py: turn a Render .env export into the Secret Manager payload.

The fake values below are obviously fake; the tool itself never prints values.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "infra" / "secrets" / "entorno.py"

spec = importlib.util.spec_from_file_location("entorno", SCRIPT)
entorno = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entorno)

COMPLETO = """\
# Render export
DATABASE_URL="postgresql://u:p@host/db?sslmode=require"
CLAUDE_API_KEY=fake-claude
GROQ_API_KEY='fake-groq'
NOTION_TOKEN=fake-notion
CLAVE_MAQUINA=fake-machine
OIDC_AUDIENCIA=fake-aud
OIDC_EMISORES=https://accounts.google.com
export CORS_ORIGENES=https://empleo.cookyourwebai.es,http://localhost:3000

EQUALS_INSIDE=a=b=c
"""


def test_outer_quotes_are_stripped_because_from_env_file_keeps_them():
    env = entorno.parse(COMPLETO)
    assert env["DATABASE_URL"] == "postgresql://u:p@host/db?sslmode=require"
    assert env["GROQ_API_KEY"] == "fake-groq"


def test_comments_blank_lines_and_export_are_ignored_and_equals_survive():
    env = entorno.parse(COMPLETO)
    assert env["CORS_ORIGENES"].startswith("https://empleo.cookyourwebai.es")
    assert env["EQUALS_INSIDE"] == "a=b=c"
    assert len(env) == 9


def test_inner_or_unbalanced_quotes_are_kept_verbatim():
    env = entorno.parse("A=\"x\nB=it's\nC='a'b'\n")
    assert env == {"A": '"x', "B": "it's", "C": "a'b"}


def test_a_duplicated_name_is_an_error_not_a_silent_override():
    with pytest.raises(ValueError, match="DUP"):
        entorno.parse("DUP=1\nDUP=2\n")


def test_a_line_that_is_not_name_equals_value_is_an_error_naming_the_line_only():
    with pytest.raises(ValueError) as exc:
        entorno.parse("OK=1\nthis is a secret value\n")
    assert "line 2" in str(exc.value)
    assert "secret value" not in str(exc.value)


def test_a_complete_env_has_no_problems():
    assert entorno.problems(entorno.parse(COMPLETO)) == []


def test_missing_or_empty_required_names_are_reported_by_name():
    env = entorno.parse(COMPLETO.replace("NOTION_TOKEN=fake-notion", "NOTION_TOKEN="))
    del env["CLAVE_MAQUINA"]
    found = entorno.problems(env)
    assert any("NOTION_TOKEN" in p for p in found)
    assert any("CLAVE_MAQUINA" in p for p in found)


def test_cors_must_allow_the_panel():
    env = entorno.parse(COMPLETO)
    env["CORS_ORIGENES"] = "http://localhost:3000"
    assert any("CORS_ORIGENES" in p for p in entorno.problems(env))


def run_cli(*args, stdin_tty=False):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def test_names_prints_names_and_never_values(tmp_path):
    f = tmp_path / "x.env"
    f.write_text(COMPLETO)
    proc = run_cli("names", str(f))
    assert proc.returncode == 0, proc.stderr
    assert "CLAUDE_API_KEY" in proc.stdout
    for value in ("fake-claude", "fake-groq", "u:p@host", "fake-machine"):
        assert value not in proc.stdout + proc.stderr


def test_json_writes_the_payload_to_a_pipe(tmp_path):
    f = tmp_path / "x.env"
    f.write_text(COMPLETO)
    proc = run_cli("json", str(f))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["GROQ_API_KEY"] == "fake-groq"


def test_an_incomplete_env_is_refused_before_any_output(tmp_path):
    f = tmp_path / "x.env"
    f.write_text("CLAUDE_API_KEY=fake-claude\n")
    proc = run_cli("json", str(f))
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "DATABASE_URL" in proc.stderr
    assert "fake-claude" not in proc.stderr


def test_values_are_never_written_to_a_terminal(monkeypatch, capsys, tmp_path):
    f = tmp_path / "x.env"
    f.write_text(COMPLETO)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert entorno.main(["json", str(f)]) == 2
    out = capsys.readouterr()
    assert "fake-claude" not in out.out + out.err
