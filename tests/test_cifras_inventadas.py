"""TDD - detectar cifras que el LLM se inventa y no estan en el CV Master.

Caso real (22jul2026): el CV EN generado decia "a global B2C and B2B car-rental
platform serving millions of users". "millions" NO esta en el Master. El prompt
YA prohibia inventar metricas y el modelo lo hizo igual: por eso se verifica la
salida en vez de confiar en la instruccion.
"""
import cv_server_railway as srv

MASTER = """Frontend Tech Lead con 10+ años de experiencia.
Plataforma de alta disponibilidad con mas de 166.000 usuarios registrados.
Responsable unico del frontend durante 8 años, 2017 - 2025.
Pipeline multilingue a 4 idiomas."""


def test_cifra_presente_en_el_master_no_se_marca():
    assert srv.detectar_cifras_no_respaldadas("Plataforma con 166.000 usuarios", MASTER) == []


def test_mismo_numero_con_otro_formato_se_considera_respaldado():
    # El master escribe 166.000 (es) y el CV en ingles 166,000. Es el MISMO dato.
    assert srv.detectar_cifras_no_respaldadas("platform with 166,000 users", MASTER) == []


def test_cifra_ausente_del_master_se_marca():
    assert "500" in srv.detectar_cifras_no_respaldadas("Lidere un equipo de 500 personas", MASTER)


def test_magnitud_textual_inventada_se_marca():
    # El caso real que disparo todo esto.
    encontradas = srv.detectar_cifras_no_respaldadas("platform serving millions of users", MASTER)
    assert "millions" in encontradas


def test_magnitud_textual_presente_en_el_master_no_se_marca():
    master = MASTER + "\nPlataforma con millones de usuarios."
    assert srv.detectar_cifras_no_respaldadas("Plataforma con millones de usuarios", master) == []


def test_los_años_no_se_marcan_como_cifras_inventadas():
    assert srv.detectar_cifras_no_respaldadas("2002 - 2008 en varias empresas", MASTER) == []


def test_texto_sin_cifras_no_marca_nada():
    assert srv.detectar_cifras_no_respaldadas("Desarrollo con React y TypeScript", MASTER) == []


def test_sin_master_no_puede_verificar_y_no_marca_nada():
    # Sin fuente de verdad no hay nada contra lo que contrastar: no inventamos alertas.
    assert srv.detectar_cifras_no_respaldadas("500 usuarios", "") == []


def test_porcentaje_inventado_se_marca():
    assert "40" in srv.detectar_cifras_no_respaldadas("Reduje la latencia un 40%", MASTER)
