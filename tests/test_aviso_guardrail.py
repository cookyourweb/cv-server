"""Los avisos de los guardrails tienen forma declarada, no un dict de palabra.

Por que existe esto:

`revisar()` devolvia `[{"regla": ..., "hallazgos": [...]}]`. Ese contrato no
estaba escrito en ningun sitio: `server.py` hacia `aviso["hallazgos"]` porque
alguien lo recordaba. Renombrar la clave no rompe ningun test, rompe produccion
a mitad de generar una carta y con un KeyError.

Importa AQUI y no en las tripas de los siete detectores porque este dato
**cruza la frontera del proceso**: sale por HTTP. Dentro de una funcion un dict
esta bien; saliendo por la red, la forma se declara.

Pydantic no es dependencia nueva: FastAPI ya lo arrastra (2.13.4 instalado).
Coste cero, que es justo lo que no pasaba con LiteLLM (ver ADR-004).

El test que de verdad protege es `test_el_json_que_sale_no_cambia_de_forma`:
el endpoint es Flask con `jsonify`, y un modelo Pydantic NO se serializa solo.
Sin ese test, este refactor rompe a cualquier cliente que ya lea la respuesta.
"""
import pytest
from pydantic import ValidationError

import guardrails as gr


def test_revisar_devuelve_avisos_con_forma_declarada():
    """Se accede por atributo, no por clave adivinada."""
    master = "Vue.js durante 8 anos en Bitcode."
    cv = "Experiencia con Django y Kubernetes."

    avisos = gr.revisar(cv, master, gr.CV)

    assert avisos, "el CV inventa tecnologias: tenia que avisar"
    for aviso in avisos:
        assert isinstance(aviso, gr.Aviso)
        assert isinstance(aviso.regla, str) and aviso.regla
        assert isinstance(aviso.hallazgos, list)
        assert all(isinstance(h, str) for h in aviso.hallazgos)


def test_un_aviso_mal_formado_se_rechaza_al_construirlo():
    """La validacion ocurre al crear el objeto, no cuando alguien lo lee."""
    with pytest.raises(ValidationError):
        gr.Aviso(regla="cifras", hallazgos="esto tenia que ser una lista")


def test_un_aviso_no_admite_campos_que_nadie_declaro():
    """Un typo en el nombre de un campo es un error, no un campo nuevo."""
    with pytest.raises(ValidationError):
        gr.Aviso(regla="cifras", hallazgos=[], hallazgoss=["typo"])


def test_el_json_que_sale_no_cambia_de_forma():
    """EL TEST QUE PROTEGE A QUIEN YA CONSUME LA API.

    La respuesta HTTP tiene que seguir siendo exactamente
    `[{"regla": str, "hallazgos": [str]}]`. Si este test se cae, el refactor
    rompio el contrato de la red aunque el codigo Python quede mas bonito.
    """
    master = "Vue.js durante 8 anos en Bitcode."
    cv = "Experiencia con Django y Kubernetes."

    avisos = gr.revisar(cv, master, gr.CV)
    como_json = [a.model_dump() for a in avisos]

    assert como_json
    for entrada in como_json:
        assert set(entrada) == {"regla", "hallazgos"}, (
            f"la forma del JSON cambio: {sorted(entrada)}"
        )
