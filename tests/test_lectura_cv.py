"""lectura_cv: type by magic bytes, hard limits, text extraction (spec S3.3 to S3.8).

Pure tests: files are built in memory (see fabrica_de_cvs.py). The sentinel proves that
no error message, repr or exception chain carries a byte of the uploaded content.
"""
import pytest
from fabrica_de_cvs import (CV_EN, CV_ES, docx_bomba, docx_con_parrafos, pdf_cifrado, pdf_con_texto,
                            pdf_escaneado, zip_con)

import lectura_cv
from lectura_cv import ErrorDeLectura, detectar_idioma, leer_cv

CENTINELA = "CENTINELA-CONTENIDO-PRIVADO-7731"


def _codigo(datos: bytes) -> str:
    with pytest.raises(ErrorDeLectura) as capturado:
        leer_cv(datos)
    return capturado.value.codigo


# --- valid files ----------------------------------------------------------------------------

def test_a_pdf_is_read_as_pdf_with_its_text():
    leido = leer_cv(pdf_con_texto(CV_ES))
    assert leido.formato == "pdf"
    assert "Desarrolladora frontend" in leido.texto and "años" in leido.texto
    assert leido.caracteres == len(leido.texto) >= 300


def test_a_docx_is_read_as_docx_with_paragraphs_and_tables():
    leido = leer_cv(docx_con_parrafos(CV_EN, celdas=("Skills", "Angular")))
    assert leido.formato == "docx"
    assert "Frontend developer" in leido.texto and "Angular" in leido.texto


def test_the_language_follows_the_text():
    assert leer_cv(pdf_con_texto(CV_ES)).idioma == "es"
    assert leer_cv(docx_con_parrafos(CV_EN)).idioma == "en"


@pytest.mark.parametrize("texto, esperado", [
    ("", "es"), ("12345 ??", "es"),                       # no signal: Spanish, like the offers
    ("the team and the work of our company with the client", "en"),
    ("el equipo y el trabajo de la empresa con los clientes", "es"),
])
def test_language_detection_is_simple_and_deterministic(texto, esperado):
    assert detectar_idioma(texto) == esperado == detectar_idioma(texto)


# --- S3.3: size, checked before parsing ----------------------------------------------------------

def test_S3_3_one_byte_over_the_limit_is_refused_without_parsing(monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("an oversize file must not be parsed")
    monkeypatch.setattr(lectura_cv, "_extraer_pdf", prohibido)
    monkeypatch.setattr(lectura_cv, "_extraer_docx", prohibido)
    assert _codigo(b"%PDF-" + b"0" * (lectura_cv.LIMITE_BYTES - 4)) == "tamano"
    assert _codigo(b"PK\x03\x04" + b"0" * lectura_cv.LIMITE_BYTES) == "tamano"


def test_a_file_exactly_at_the_limit_is_not_refused_for_size(monkeypatch):
    datos = pdf_con_texto(CV_ES)
    monkeypatch.setattr(lectura_cv, "LIMITE_BYTES", len(datos))
    assert leer_cv(datos).formato == "pdf"
    monkeypatch.setattr(lectura_cv, "LIMITE_BYTES", len(datos) - 1)
    assert _codigo(datos) == "tamano"


# --- S3.4 / S3.5: the type is the magic bytes, never the name ---------------------------------------

@pytest.mark.parametrize("datos", [
    b"", b"MZ\x90\x00" + b"\x00" * 400, b"<html><script>alert(1)</script></html>",
    b"plain text pretending to be a CV " * 20, b"%PD", b"PK\x03",
    b" %PDF-1.4 leading space",
])
def test_S3_4_anything_that_is_not_a_pdf_or_a_zip_is_an_unsupported_type(datos):
    assert _codigo(datos) == "tipo"


def test_S3_5_a_zip_that_is_not_a_docx_is_an_unsupported_type():
    assert _codigo(zip_con({"notas.txt": "hola" * 200})) == "tipo"
    assert _codigo(zip_con({"xl/workbook.xml": "<x/>"})) == "tipo"


# --- S3.6: zip bomb ------------------------------------------------------------------------------------

def test_S3_6_a_docx_that_inflates_past_the_limit_is_refused_before_parsing(monkeypatch):
    bomba = docx_bomba(megas=11)
    assert len(bomba) < lectura_cv.LIMITE_BYTES  # passes the size check: only the guard can stop it

    def prohibido(*args, **kwargs):
        raise AssertionError("a zip bomb must not reach the DOCX parser")
    monkeypatch.setattr(lectura_cv, "_extraer_docx", prohibido)
    assert _codigo(bomba) == "ilegible"


def test_a_zip_with_too_many_entries_is_refused():
    muchos = zip_con({"word/document.xml": "<x/>", **{f"f{n}.txt": "a" for n in range(lectura_cv.MAX_ENTRADAS_ZIP)}})
    assert _codigo(muchos) == "ilegible"


# --- PDF limits and S3.7: unreadable files fail in a controlled way ----------------------------------------

def test_a_pdf_with_more_than_ten_pages_is_too_long():
    assert leer_cv(pdf_con_texto(CV_ES, paginas=10)).formato == "pdf"
    assert _codigo(pdf_con_texto(CV_ES, paginas=11)) == "largo"


def test_an_encrypted_pdf_is_unreadable():
    assert _codigo(pdf_cifrado()) == "ilegible"


@pytest.mark.parametrize("construir", [
    lambda: b"%PDF-1.4\n" + CENTINELA.encode() + b"\n%%EOF",
    lambda: pdf_con_texto([CENTINELA] * 30)[:-120],
    lambda: b"PK\x03\x04" + CENTINELA.encode() * 3,
    lambda: zip_con({"word/document.xml": "<w:document " + CENTINELA})[:-30],
    lambda: zip_con({"word/document.xml": "not xml " + CENTINELA * 40}),
])
def test_S3_7_a_corrupt_file_is_a_controlled_error_that_never_carries_its_content(construir):
    with pytest.raises(ErrorDeLectura) as capturado:
        leer_cv(construir())
    error = capturado.value
    assert error.codigo in {"ilegible", "tipo"}
    assert CENTINELA not in str(error) + repr(error) + repr(error.args)
    # No chained exception: a traceback printed by a logger could not leak the parser's message.
    assert error.__cause__ is None and error.__context__ is None


# --- S3.8: scanned files have no text -------------------------------------------------------------------------

def test_S3_8_a_scanned_pdf_has_no_text_and_asks_for_the_manual_form():
    assert _codigo(pdf_escaneado(2)) == "sin_texto"


def test_the_text_threshold_is_300_characters_after_trimming():
    corto = ["x" * 299]
    assert _codigo(docx_con_parrafos(corto)) == "sin_texto"
    assert _codigo(docx_con_parrafos(["   " + "x" * 299 + "   "])) == "sin_texto"
    assert leer_cv(docx_con_parrafos(["x" * 300])).caracteres == 300


def test_an_absurdly_long_text_is_refused():
    enorme = docx_con_parrafos(["palabra " * 40_000])
    assert _codigo(enorme) == "largo"


# --- libraries stay quiet ------------------------------------------------------------------------------------------

def test_parsing_does_not_let_the_libraries_log_or_warn(caplog, recwarn):
    import logging
    with caplog.at_level(logging.DEBUG):
        for datos in (b"%PDF-1.4\n" + CENTINELA.encode(), pdf_con_texto(CV_ES)[:-60]):
            with pytest.raises(ErrorDeLectura):
                leer_cv(datos)
    assert CENTINELA not in caplog.text
