"""TDD - detectar tecnologias que el CV generado atribuye a la candidata y que
NO estan en su CV Master.

Caso real (23jul2026): la oferta de Tenth Revolution pedia "entornos PHP/Symfony o
templating server-side (Twig, Blade)". Veronica NO tiene esa experiencia. El CV
generado coló "experiencia en templating server-side (contexto de integracion con
arquitecturas PHP/Symfony)": una formula ambigua que no es exactamente mentira pero
que en la bandeja de un recruiter se lee como experiencia.

El prompt YA prohibe inventar. Lo hizo igual. Por eso se verifica la SALIDA, igual
que con las cifras.
"""
import cv_server_railway as srv

MASTER = """Frontend Tech Lead con 20 años de experiencia.
Stack: React, TypeScript, Vue.js, Angular, JavaScript, HTML5, CSS3, Node.js.
Backend con Python y FastAPI. Bases de datos MongoDB y PostgreSQL.
Integracion de APIs REST. Testing con Jest y Cypress. Docker y Git.
Desarrollo asistido por IA con Claude Code y Cursor."""


def test_tecnologia_del_master_no_se_marca():
    assert srv.detectar_tecnologias_no_respaldadas("Desarrollo con React y TypeScript", MASTER) == []


def test_tecnologia_ausente_del_master_se_marca():
    # El caso real que disparo todo esto.
    encontradas = srv.detectar_tecnologias_no_respaldadas(
        "Experiencia en arquitecturas PHP/Symfony", MASTER)
    assert "PHP" in encontradas
    assert "Symfony" in encontradas


def test_templating_server_side_ajeno_se_marca():
    encontradas = srv.detectar_tecnologias_no_respaldadas(
        "Templating server-side con Twig y Blade", MASTER)
    assert "Twig" in encontradas
    assert "Blade" in encontradas


def test_la_capitalizacion_no_importa():
    # El master dice "React"; el CV en minusculas sigue estando respaldado.
    assert srv.detectar_tecnologias_no_respaldadas("desarrollo con react", MASTER) == []


def test_tecnologia_con_punto_en_el_nombre_respaldada():
    # "Node.js" esta en el master. No debe marcarse ni como "Node" ni como "Node.js".
    assert srv.detectar_tecnologias_no_respaldadas("Backend con Node.js", MASTER) == []


def test_tecnologia_con_caracteres_especiales_se_marca():
    encontradas = srv.detectar_tecnologias_no_respaldadas("Desarrollo en C# y .NET", MASTER)
    assert "C#" in encontradas
    assert ".NET" in encontradas


def test_no_marca_la_parte_corta_de_un_nombre_largo():
    # "Spring Boot" no esta en el master. Se reporta una vez, no como "Spring" ademas.
    encontradas = srv.detectar_tecnologias_no_respaldadas("Microservicios con Spring Boot", MASTER)
    assert "Spring Boot" in encontradas
    assert "Spring" not in encontradas


def test_rtl_en_el_master_respalda_react_testing_library_en_el_cv():
    # Falso positivo real (23jul2026): el Master dice "RTL", el CV "React Testing
    # Library". Son lo mismo, no debe marcarse.
    master = MASTER + "\nTesting automatizado: Jest, RTL, Cypress."
    assert srv.detectar_tecnologias_no_respaldadas(
        "Automated testing with React Testing Library", master) == []
    assert srv.detectar_tecnologias_no_respaldadas("Testing con RTL", master) == []


def test_sin_master_no_puede_verificar_y_no_marca_nada():
    # Sin fuente de verdad no hay nada contra lo que contrastar: no inventamos alertas.
    assert srv.detectar_tecnologias_no_respaldadas("Experiencia con PHP", "") == []


def test_texto_sin_tecnologias_no_marca_nada():
    assert srv.detectar_tecnologias_no_respaldadas(
        "Responsable del rediseño de la experiencia de usuario", MASTER) == []


def test_regresion_la_frase_exacta_del_cv_de_tenth_revolution():
    """La frase que hubo que borrar a mano el 23jul2026.

    Es la prueba de que el guardrail pilla la formula ambigua, no solo el
    "tengo experiencia en PHP" descarado."""
    frase = ("Experiencia en templating server-side (contexto de integracion con "
             "arquitecturas PHP/Symfony)")
    encontradas = srv.detectar_tecnologias_no_respaldadas(frase, MASTER)
    assert "PHP" in encontradas
    assert "Symfony" in encontradas


def test_palabra_normal_que_contiene_el_nombre_de_una_tecnologia_no_se_marca():
    # "Blade" dentro de "Bladerunner" no es la tecnologia.
    assert srv.detectar_tecnologias_no_respaldadas("Proyecto Bladerunner", MASTER) == []
