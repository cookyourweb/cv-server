"""TDD - la EXPERIENCIA se lee como una trayectoria de PUESTOS, no de empresas.

Caso real, 24jul2026. Verónica revisó los CV regenerados de N-iX y Revolut y detectó
que la experiencia no cuenta la historia: quiere leer "Tech Lead en Bitcode, Frontend en
Mutualidad, antes diseñadora". El puesto es la narrativa de una carrera; la empresa es
el contexto.

Los CV salieron así:

    CookYourWeb
    AI Engineer & Full-Stack Tech Lead
    2025 - Present

y NO fue el modelo desviándose: el propio bloque de formato del prompt pedía
`[Empresa] — [Ciudad]` y debajo `[Puesto]`. El modelo obedeció. Además la ciudad nunca
se rellenaba, porque el CV Master no guarda ciudad por puesto.

Segundo fallo encontrado de paso, en el render del DOCX
(`generar_docx_con_cabecera`): la línea de puesto/empresa se detecta por llevar guion
largo o medio y medir menos de 100 caracteres, y esa comprobación va ANTES que la de
fecha. El bloque de formato pedía las fechas como `[Fecha inicio] – [Fecha fin]`, con
guion MEDIO: esa línea entraba por la rama de empresa y se renderizaba en negrita de
10pt en vez de cursiva gris. Se arregla en la plantilla (guion normal en las fechas),
que es más seguro que reordenar las ramas del render.
"""
import pathlib
import re

# Dos fuentes: la PLANTILLA del prompt sigue en el servidor, y el RENDER del DOCX
# se mudo a `docx_render.py` el 28-ago-2026. Cada test mira donde vive lo suyo.
RAIZ = pathlib.Path(__file__).resolve().parent.parent
SRC = (RAIZ / "server.py").read_text(encoding="utf-8")
RENDER = (RAIZ / "docx_render.py").read_text(encoding="utf-8")


def test_el_puesto_va_antes_que_la_empresa_en_los_dos_idiomas():
    """El orden de la plantilla es el orden que sale en el CV."""
    assert "[Role] — [Company]" in SRC, (
        "El bloque de formato en inglés debe pedir PUESTO — EMPRESA, en ese orden."
    )
    assert "[Puesto] — [Empresa]" in SRC, (
        "El bloque de formato en español debe pedir PUESTO — EMPRESA, en ese orden."
    )


def test_ya_no_se_pide_la_empresa_delante():
    """Regresión: la plantilla vieja ponía la empresa (y una ciudad que nunca llegaba)."""
    for viejo in ("[Company] — [City]", "[Empresa] — [Ciudad]"):
        assert viejo not in SRC, (
            f"Queda la plantilla vieja {viejo!r}: pone la empresa delante del puesto y "
            "pide una ciudad que el CV Master no tiene por puesto."
        )


def test_el_puesto_y_la_empresa_van_en_una_sola_linea():
    """Antes eran tres líneas (empresa, puesto, fecha). Ahora dos."""
    for plantilla in ("[Role] — [Company]", "[Puesto] — [Empresa]"):
        i = SRC.index(plantilla)
        siguiente = SRC[i + len(plantilla):].splitlines()[1].strip()
        assert siguiente.startswith(("[Start date]", "[Fecha inicio]")), (
            f"Después de {plantilla!r} debe venir directamente la fecha, no otra línea. "
            f"Vino: {siguiente!r}"
        )


def test_las_fechas_no_llevan_guion_largo_ni_medio():
    """Si la línea de fechas lleva — o –, el render la toma por línea de empresa.

    `generar_docx_con_cabecera` decide por el guion antes que por el año, así que una
    fecha con guion medio sale en negrita de 10pt en lugar de cursiva gris."""
    for plantilla in ("[Start date]", "[Fecha inicio]"):
        i = SRC.index(plantilla)
        linea = SRC[i:].splitlines()[0]
        assert "—" not in linea and "–" not in linea, (
            f"La línea de fechas {linea!r} lleva guion largo o medio: el render la "
            "confundirá con la línea de puesto/empresa."
        )


def test_el_render_sigue_detectando_la_linea_de_puesto_por_el_guion():
    """El guion largo sigue siendo el marcador: si se quita, se pierde la negrita.

    Documentado en PROMPT-ADAPTACION-CV.md ('no metas un saneado tipográfico global
    antes de parsear el DOCX')."""
    assert re.search(r'if \("—" in linea or "–" in linea\)', RENDER), (
        "Cambió la detección de la línea de puesto/empresa en el render del DOCX: "
        "revisa que la plantilla siga usando el guion largo como marcador."
    )
