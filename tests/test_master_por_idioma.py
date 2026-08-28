"""TDD - eleccion del CV master segun idioma, y reporte del master REALMENTE usado.

Bug: /generar-cv reportaba siempre `cv_master_url` (el master EN) aunque el CV
se hubiera generado en español desde el master ES. La eleccion era correcta;
lo que mentia era la respuesta.
"""
import cv_server_railway as srv

EN = "https://docs.google.com/document/d/EN123/edit"
ES = "https://docs.google.com/document/d/ES456/edit"


def _usuario(**over):
    u = {"cv_master_url": EN, "cv_master_url_es": ES, "cv_master_file_id": ""}
    u.update(over)
    return u


def test_idioma_es_elige_el_master_es():
    assert srv.elegir_master(_usuario(), "es").url == ES


def test_idioma_en_elige_el_master_en():
    assert srv.elegir_master(_usuario(), "en").url == EN


def test_sin_master_es_cae_al_en():
    assert srv.elegir_master(_usuario(cv_master_url_es=""), "es").url == EN


def test_extrae_el_file_id_de_la_url():
    assert srv.elegir_master(_usuario(), "es").file_id == "ES456"


def test_file_id_explicito_gana_en_ingles():
    u = _usuario(cv_master_file_id="FID789")
    assert srv.elegir_master(u, "en").file_id == "FID789"


def test_sin_ningun_master_devuelve_vacio():
    u = _usuario(cv_master_url="", cv_master_url_es="")
    elegido = srv.elegir_master(u, "es")
    assert elegido.file_id == ""
    assert elegido.url == ""
