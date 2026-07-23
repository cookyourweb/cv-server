"""TDD - resolver el idioma de una oferta de forma fiable.

Caso real (23jul2026): Revolut, oferta en ingles, salio la carta en espanol. El CV
acerto y la carta no, para la MISMA oferta. Causa: el idioma se detectaba de la
DESCRIPCION, que la tarea programada reescribe siempre en espanol, asi que ahogaba
la senal del titulo, que si viene en el idioma del anuncio.

Regla: el PUESTO manda sobre la descripcion. Y un idioma explicito (body o campo
Idioma de Notion) manda sobre cualquier deteccion.
"""
import cv_server_railway as srv

DESC_ES = ("Buscamos un ingeniero con experiencia en desarrollo de aplicaciones. "
           "Ofrecemos un puesto estable, jornada completa, equipo consolidado y "
           "posibilidades de crecimiento. Imprescindible nivel alto y capacidad de "
           "trabajo en equipo.")


def test_puesto_en_ingles_gana_a_descripcion_en_espanol():
    # El caso Revolut: titulo ingles, notas reescritas en espanol.
    assert srv.idioma_de_oferta("Applied AI Engineer", DESC_ES, "Revolut") == "en"


def test_puesto_en_espanol_da_espanol():
    assert srv.idioma_de_oferta("Programador Senior Backend", DESC_ES, "Arelance") == "es"


def test_titulo_con_senal_neta_manda_sobre_la_descripcion():
    # El titulo en ingles gana aunque la descripcion sea muy española: la descripcion
    # la reescribe la tarea en español y NO es señal fiable del idioma del anuncio.
    # Los casos limite (oferta española titulada en ingles) los corrige el campo
    # Idioma de Notion, que manda sobre esta deteccion.
    desc_muy_es = DESC_ES + (" Desarrollador con conocimientos de gestion, liderazgo, "
                             "programador de aplicaciones, requisitos imprescindibles.")
    assert srv.idioma_de_oferta("Senior Frontend Engineer", desc_muy_es, "Indra") == "en"


def test_sin_puesto_cae_a_la_descripcion():
    assert srv.idioma_de_oferta("", DESC_ES, "") == "es"


def test_todo_vacio_devuelve_espanol():
    # Mercado principal de la usuaria: el empate y el vacio caen a espanol.
    assert srv.idioma_de_oferta("", "", "") == "es"


def test_puesto_ingles_claro_todo_ingles():
    assert srv.idioma_de_oferta(
        "Senior Full-Stack Engineer",
        "We are looking for a developer with strong experience. Remote role.",
        "Trimble") == "en"
