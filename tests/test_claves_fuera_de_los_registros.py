"""TDD - Ninguna clave de proveedor llega a los registros.

Caso real (2oct2026), encontrado al revisar ADR-004: la clave de Gemini viajaba
en la URL (`?key=...`). Cuando Gemini fallaba, `requests` metia la URL entera en
el mensaje de `HTTPError`, y el `logger.warning(..., e)` de la cascada la
escribia en los registros de Render. Cada fallo de Gemini publicaba la clave a
quien pudiera leer los logs.

Dos defensas, y se prueban las dos:
1. La clave va en cabecera (`x-goog-api-key`, documentado por Google), nunca en
   la URL.
2. Los errores de los proveedores se registran por su tipo y su codigo HTTP,
   nunca con `str(e)`, porque el mensaje lo arma una libreria de terceros y no
   controlamos que lleva dentro.
"""
import logging

import pytest
import requests

import llm

CLAVE_GEMINI = "AIzaSECRETO-de-prueba-123"
CLAVE_GROQ = "gsk_SECRETO-de-prueba-456"
CLAVE_CLAUDE = "sk-ant-SECRETO-de-prueba-789"


class _Respuesta:
    def __init__(self, url):
        self.url = url
        self.status_code = 500

    def raise_for_status(self):
        # Igual que requests: el mensaje lleva la URL completa.
        raise requests.HTTPError(f"500 Server Error for url: {self.url}", response=self)


@pytest.fixture
def todo_falla(monkeypatch):
    peticiones = []

    def post(url, params=None, headers=None, **k):
        completa = url + ("?" + "&".join(f"{a}={b}" for a, b in params.items()) if params else "")
        peticiones.append({"url": completa, "headers": headers or {}})
        return _Respuesta(completa)

    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm, "GROQ_API_KEY", CLAVE_GROQ)
    monkeypatch.setattr(llm, "GEMINI_API_KEY", CLAVE_GEMINI)
    monkeypatch.setattr(llm, "CLAUDE_API_KEY", CLAVE_CLAUDE)
    return peticiones


def _cascada():
    return llm.BACKENDS["casera"]()


def test_la_clave_de_gemini_no_va_en_la_url(todo_falla):
    with pytest.raises(RuntimeError):
        _cascada().completar("hola")
    gemini = [p for p in todo_falla if "generativelanguage" in p["url"]]
    assert gemini, "la cascada deberia haber probado Gemini"
    assert CLAVE_GEMINI not in gemini[0]["url"]
    assert gemini[0]["headers"].get("x-goog-api-key") == CLAVE_GEMINI


def test_ninguna_clave_aparece_en_los_registros(todo_falla, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(RuntimeError) as exc:
        _cascada().completar("hola")
    for clave in (CLAVE_GEMINI, CLAVE_GROQ, CLAVE_CLAUDE):
        assert clave not in caplog.text
        assert clave not in str(exc.value)


def test_el_registro_dice_que_fallo_y_con_que_codigo(todo_falla, caplog):
    caplog.set_level(logging.WARNING)
    with pytest.raises(RuntimeError):
        _cascada().completar("hola")
    assert "HTTPError" in caplog.text
    assert "500" in caplog.text


def test_describir_error_no_usa_el_mensaje():
    e = requests.HTTPError(f"500 for url: https://x/?key={CLAVE_GEMINI}", response=_Respuesta("u"))
    descripcion = llm.describir_error(e)
    assert CLAVE_GEMINI not in descripcion
    assert "HTTPError" in descripcion and "500" in descripcion
