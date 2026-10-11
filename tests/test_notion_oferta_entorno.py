"""The offers database id comes from the environment only: no id is baked into the code.

Without it every offer function degrades (None / False / a network-style error) instead of
silently talking to a database nobody configured.
"""
import importlib.util
import re
from pathlib import Path

import pytest
import requests

RAIZ = Path(__file__).resolve().parent.parent
FORMA_DE_ID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.I)


@pytest.fixture
def sin_base_de_ofertas(monkeypatch):
    """A private copy of notion.py imported with the variable unset.

    Not importlib.reload: that would replace classes (ErrorDeNotion) of the module the
    other tests share.
    """
    monkeypatch.delenv("NOTION_DB_OFERTAS", raising=False)
    spec = importlib.util.spec_from_file_location("notion_sin_entorno", RAIZ / "notion.py")
    copia = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copia)
    return copia


def test_the_default_is_empty(sin_base_de_ofertas):
    assert sin_base_de_ofertas.NOTION_DB_OFERTAS == ""


@pytest.mark.parametrize("fichero", ["notion.py", "server.py"])
def test_no_database_id_is_hardcoded_next_to_the_variable(fichero):
    for linea in (RAIZ / fichero).read_text(encoding="utf-8").splitlines():
        if "NOTION_DB_OFERTAS" in linea and "os.getenv" in linea:
            assert not FORMA_DE_ID.search(linea), fichero


def test_lookups_degrade_without_a_network_call(sin_base_de_ofertas, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("no request may leave without a database id")
    monkeypatch.setattr(requests, "post", prohibido)
    assert sin_base_de_ofertas.buscar_oferta_en_notion("Acme", "Dev") is None
    assert sin_base_de_ofertas.guardar_link_cv_en_notion("Acme", "Dev", "https://drive/x", "cv.docx") is False


def test_creating_an_offer_fails_cleanly_without_a_network_call(sin_base_de_ofertas, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("no request may leave without a database id")
    monkeypatch.setattr(requests, "post", prohibido)
    with pytest.raises(requests.RequestException):
        sin_base_de_ofertas.crear_oferta_en_notion({"empresa": "Acme", "puesto": "Dev"})


def test_the_pre_production_checklist_names_the_variable():
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    checklist = readme.split("## Pre-production checklist")[1].split("\n## ")[0]
    assert "NOTION_DB_OFERTAS" in checklist and "Render" in checklist
