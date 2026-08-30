"""TDD - el prompt de la carta tiene que poder LEERSE, y decir lo que se acordo.

Caso real (30ago2026). El prompt de `/generar-carta` pedia "Maximo 250 palabras"
cuando la regla acordada el 29ago son ~70. El fallo se corrigio aquel dia EN LA
CONVERSACION, nunca en el codigo, y siguio vivo en produccion un dia entero.

Nadie lo vio porque el prompt era un f-string dentro de una funcion, en un
`server.py` de 1267 lineas: ningun test podia leerlo. Es el mismo patron que el
`2 full paragraphs (4-6 lines each)` que daba resumenes de 180 palabras.

Un bug de prompt NO da error: da un resultado peor. Solo lo caza un humano
leyendo, y por eso hay que poder testearlo.

Estos tests NO llaman al modelo. Comprueban lo que el prompt PIDE, que es lo
unico que esta bajo control del repositorio.
"""
import re

import server as srv


def test_el_prompt_de_la_carta_se_puede_leer_desde_fuera():
    # Si esto falla, el prompt volvio a esconderse dentro de una funcion.
    assert isinstance(srv.PROMPT_CARTA, str)
    assert len(srv.PROMPT_CARTA) > 200, "demasiado corto para ser el prompt"


def test_no_pide_mas_de_100_palabras():
    # La regla son ~70. Se deja margen, pero 250 no puede volver a colarse.
    cifras = [int(n) for n in re.findall(r"(\d+)\s+palabras", srv.PROMPT_CARTA)]
    assert cifras, "el prompt no dice cuantas palabras quiere"
    assert max(cifras) <= 100, f"pide {max(cifras)} palabras; la regla son ~70"


def test_pide_una_sola_ancla_y_remite_al_cv():
    # 29ago2026: "presentarse, decir que encaja y remitir al CV". Una sola ancla,
    # nunca una lista. Una carta que lo cuenta todo compite con el CV y pierde.
    p = srv.PROMPT_CARTA.lower()
    assert "cv" in p, "el prompt no dice que remita al CV"
    assert re.search(r"una sola|un solo|una unica|una única", p), \
        "el prompt no limita a UNA ancla: volvera a listar proyectos"


def test_sigue_prohibiendo_las_frases_vacias_de_ia():
    # Esto ya funcionaba. El test existe para que un refactor no se lo lleve.
    p = srv.PROMPT_CARTA.lower()
    assert "apasionada" in p and "proactiva" in p


def test_el_prompt_se_rellena_sin_perder_las_reglas():
    # PROMPT_CARTA es una plantilla: al rellenarla no puede romperse ni perder
    # el limite de palabras.
    texto = srv.PROMPT_CARTA.format(
        nombre="Veronica Serna Perez",
        contexto="CV master de prueba",
        empresa="Mindera",
        puesto="Senior AI Engineer",
        descripcion="Agentic AI",
        idioma_carta="ingles",
        instr_saludo='saludo formal generico ("Dear Hiring Team,")',
    )
    assert "Mindera" in texto and "Veronica Serna Perez" in texto
    assert "{" not in texto.replace("{{", "").replace("}}", ""), "quedan huecos sin rellenar"
    cifras = [int(n) for n in re.findall(r"(\d+)\s+palabras", texto)]
    assert max(cifras) <= 100
