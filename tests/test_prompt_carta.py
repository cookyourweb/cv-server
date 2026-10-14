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
        empresa="Acme Consulting",
        puesto="Senior AI Engineer",
        descripcion="Agentic AI",
        idioma_carta="ingles",
        instr_saludo='saludo formal generico ("Dear Hiring Team,")',
    )
    assert "Acme Consulting" in texto and "Veronica Serna Perez" in texto
    assert "{" not in texto.replace("{{", "").replace("}}", ""), "quedan huecos sin rellenar"
    cifras = [int(n) for n in re.findall(r"(\d+)\s+palabras", texto)]
    assert max(cifras) <= 100


# ── Guia de redaccion de Vero (13-oct-2026) ──────────────────────────────────
# buscartrabajo-privado/guia-redaccion-candidaturas.md. La longitud corta (~70)
# se MANTIENE por decision de Vero (14-oct); de la guia se incorpora el resto.


def test_empieza_directo_sin_introducciones_vacias():
    # Guia, punto 3: empezar por el motivo de interes o la conexion con la oferta,
    # nunca "Me dirijo a ustedes para expresar mi interes".
    p = srv.PROMPT_CARTA.lower()
    assert "me dirijo a ustedes" in p, "el prompt no prohibe la introduccion vacia"
    assert re.search(r"empieza (directamente|directo)", p), \
        "el prompt no pide empezar directo por el motivo de interes"


def test_dice_por_que_interesa_y_que_aporta():
    # Guia, punto 3: por que me interesa, que experiencia encaja, que aporto.
    p = srv.PROMPT_CARTA.lower()
    assert "por qué te interesa" in p or "por que te interesa" in p
    assert "aport" in p, "el prompt no pide decir que aporta al equipo o al producto"


def test_prohibe_las_frases_de_la_guia():
    # Guia, punto 7. Si una desaparece del prompt, volvera a salir en las cartas.
    p = srv.PROMPT_CARTA.lower()
    for frase in ("me entusiasma", "encaja perfectamente", "gran valor",
                  "altamente motivada", "dilatada trayectoria"):
        assert frase in p, f"el prompt ya no prohibe '{frase}'"


def test_honestidad_tecnica_no_convierte_requisitos_en_competencias():
    # Guia, punto 6: no convertir una tecnologia de la oferta en una competencia
    # que la candidata no tiene; si falta un requisito, conexion honesta.
    p = srv.PROMPT_CARTA.lower()
    assert "requisito" in p and "no cumpl" in p, \
        "el prompt no dice que hacer con un requisito que no se cumple"


def test_cierre_sencillo():
    # Guia, punto 3: terminar de forma sencilla, sin llamadas comerciales.
    p = srv.PROMPT_CARTA.lower()
    assert "cierre sencillo" in p or "termina de forma sencilla" in p


def test_queda_documentada_la_version_larga():
    # Decision de Vero (14-oct): la corta es la de por defecto; si se pide una
    # carta mas larga, la guia marca 100-160 palabras con 1-2 ejemplos y por que
    # encaja. La nota tiene que estar junto al prompt para que no se pierda.
    import inspect
    fuente = inspect.getsource(srv)
    assert "VERSION LARGA" in fuente and "100-160" in fuente, \
        "falta la nota de la version larga junto a PROMPT_CARTA"


def test_estructura_combinada_en_la_carta_corta():
    # Decision de Vero (14-oct): corta, pero con los cuatro pasos combinados:
    # presentarse, por que interesa, que experiencia aporta y por que encaja.
    p = srv.PROMPT_CARTA.lower()
    assert re.search(r"pres[eé]ntate", p), "el prompt no pide presentarse"
    assert "por qué te interesa" in p
    assert re.search(r"qu[eé]\s+experiencia\s+concreta\s+aportas", p)
    assert re.search(r"por\s+qu[eé]\s+encajas", p), "el prompt no pide decir por que encaja"
