"""El resumen del CV se lee en seis segundos o no se lee.

Historia de por que existe este test:

29-ago-2026, CV para la oferta de Social You. El resumen salio con **180
palabras en dos parrafos densos**. No fue culpa del modelo: el prompt pedia
literalmente `2 full paragraphs (4-6 lines each)`, o sea entre ocho y doce
lineas. El modelo obedecio.

El dano es que entierra lo bueno. Quien criba mira el titular y las tres
primeras lineas; si ahi no encuentra el encaje, no baja. Y la experiencia ya
esta detallada mas abajo, asi que el resumen largo ademas repite.

Este test es un CANARIO SOBRE LA INSTRUCCION, no sobre la salida: comprobar la
longitud del texto generado exigiria llamar al modelo, que cuesta dinero y no es
determinista. Lo que se fija aqui es que el prompt no vuelva a pedir dos
parrafos y que siga imponiendo un tope de palabras. Mismo patron que
`test_modelos_retirados.py`: se vigila la configuracion, que es donde se cuela
el fallo.
"""
import re

import server as srv

PLANTILLAS = {
    "PROFESSIONAL SUMMARY": srv.PROMPT_ESTRUCTURA_EN,
    "PERFIL PROFESIONAL":   srv.PROMPT_ESTRUCTURA_ES,
}


def _bloque_del_resumen(plantilla: str, encabezado: str) -> str:
    """El corchete de instrucciones que sigue al encabezado del resumen."""
    inicio = plantilla.index(encabezado) + len(encabezado)
    return plantilla[inicio:plantilla.index("]", inicio) + 1]


def test_ninguna_plantilla_pide_dos_parrafos_para_el_resumen():
    for encabezado, plantilla in PLANTILLAS.items():
        bloque = _bloque_del_resumen(plantilla, encabezado).lower()
        assert "2 full paragraphs" not in bloque, encabezado
        assert "2 párrafos" not in bloque and "2 parrafos" not in bloque, encabezado
        assert "dos párrafos" not in bloque and "two paragraphs" not in bloque, encabezado


def test_las_dos_plantillas_ponen_un_tope_de_palabras():
    """Sin numero, 'breve' no significa nada para un modelo."""
    for encabezado, plantilla in PLANTILLAS.items():
        bloque = _bloque_del_resumen(plantilla, encabezado)
        topes = [int(n) for n in re.findall(r"\b(\d{2,3})\b", bloque)]
        assert topes, f"{encabezado}: la instruccion no lleva ningun numero"
        assert any(t <= 90 for t in topes), (
            f"{encabezado}: el tope mas bajo es {min(topes)} palabras, "
            "demasiado para un resumen que se lee en seis segundos"
        )


def test_el_resumen_sigue_siendo_un_arco_y_no_una_lista_de_tecnologias():
    """No vale arreglar la longitud rompiendo la narrativa.

    Las reglas de `RESUMEN` mandan contar el arco (de donde viene, como
    evoluciono, que la define hoy). Acortar no puede convertir el resumen en un
    listado de herramientas.
    """
    for plantilla in PLANTILLAS.values():
        assert "EVOLUCIÓN PROFESIONAL" in plantilla or "EVOLUCION PROFESIONAL" in plantilla
