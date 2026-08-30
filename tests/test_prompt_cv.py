"""TDD - el prompt del CV tiene que poder LEERSE, y conservar sus reglas duras.

Caso real (30ago2026). El prompt de `/generar-cv` son 133 lineas dentro de un
f-string, en un `server.py` de 1267 lineas. Ningun test podia leerlo.

Ya mordio una vez: pedia `2 full paragraphs (4-6 lines each)` y salian resumenes
de 180 palabras. Se arreglo el 29ago (commit 367b424) leyendolo A MANO, porque no
habia otra forma.

Estas reglas son el resultado de meses de correcciones sobre CVs reales. Un
refactor que se lleve una por delante no da error: da un CV peor, y solo lo caza
una persona leyendo. Por eso se fijan aqui.

Los tests NO llaman al modelo. Comprueban lo que el prompt PIDE, que es lo unico
bajo control del repositorio.
"""
import server as srv


def test_el_prompt_del_cv_se_puede_leer_desde_fuera():
    assert isinstance(srv.PROMPT_CV, str)
    assert len(srv.PROMPT_CV) > 2000, "demasiado corto para ser el prompt del CV"


def test_conserva_la_regla_maestra_de_proyeccion():
    # De esta se derivan casi todas las demas: adaptar es PROYECTAR la experiencia
    # real sobre la oferta, no construir una identidad nueva.
    assert "REGLA MAESTRA" in srv.PROMPT_CV
    assert "PROYECCIÓN, NO IDENTIDAD NUEVA" in srv.PROMPT_CV


def test_prohibe_inventar():
    # La defensa principal contra la alucinacion. Sin esto, los guardrails de
    # `guardrails.py` pasan de ser una red a ser el unico control.
    assert "NO INVENTAR NUNCA" in srv.PROMPT_CV


def test_el_resumen_no_gira_alrededor_del_proyecto_propio():
    # Correccion real: el resumen se iba detras del proyecto personal y tapaba
    # veinte anos de trayectoria.
    assert "EL RESUMEN NUNCA GIRA ALREDEDOR DEL PROYECTO PROPIO" in srv.PROMPT_CV


def test_respeta_el_bloque_posicionamiento_del_master():
    # El master puede declarar lo que la candidata NO es. Ignorarlo abre frentes
    # que no puede defender en entrevista.
    assert "POSICIONAMIENTO" in srv.PROMPT_CV


def test_escribe_la_accion_no_el_efecto_atribuido():
    # Sin esto aparecen impactos inventados ("mejore la conversion un 30%").
    assert "NUNCA el efecto que se le atribuye" in srv.PROMPT_CV


def test_el_prompt_se_rellena_sin_perder_las_reglas():
    texto = srv.PROMPT_CV.format(
        contexto_candidato="CV master de prueba",
        empresa="Mindera",
        puesto="Senior AI Engineer",
        descripcion="Agentic AI, evaluation infrastructure",
        idioma_nombre="inglés",
        bloque_formato=srv.PROMPT_ESTRUCTURA_EN,
    )
    assert "Mindera" in texto and "Senior AI Engineer" in texto
    assert "{" not in texto.replace("{{", "").replace("}}", ""), "quedan huecos sin rellenar"
    assert "NO INVENTAR NUNCA" in texto
    assert "REGLA MAESTRA" in texto
