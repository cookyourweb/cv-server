"""TDD - anadir un guardrail no puede obligar a modificar los endpoints.

Hoy `/generar-cv` y `/generar-carta` ENUMERAN los detectores a mano. Para meter
el septimo hay que editar los dos endpoints y decidir en cada uno si aplica. Eso
es exactamente lo que el principio abierto/cerrado dice que no hagas: el sistema
deberia estar abierto a extension y cerrado a modificacion.

Ademas resuelve un problema real que ya existe: hoy la eleccion de que guardrail
aplica a la carta vive en el endpoint, con un comentario explicando por que
`skills_no_respaldadas` queda fuera. Esa decision la sabe el guardrail sobre si
mismo, no quien lo llama.

QUE NO ENTRA EN EL REGISTRO, y es una decision, no un olvido:
- `detectar_titular_fuera_de_contrato` recibe el TITULAR, no el texto completo.
- `evaluar_descripcion_oferta` mira la ENTRADA y devuelve un dict, no una lista.

Meterlos a la fuerza obligaria a un contrato mas gordo que ninguno de los dos
necesita. Es segregacion de interfaces: nadie implementa lo que no usa.
"""
import guardrails as g


def test_todos_los_guardrails_cumplen_el_contrato():
    for gr in g.GUARDRAILS:
        assert isinstance(gr.nombre, str) and gr.nombre
        assert isinstance(gr.aplica_a, frozenset) and gr.aplica_a
        assert callable(gr.revisar)


def test_son_sustituibles_entre_si():
    # Liskov: cualquiera de ellos vale donde se espera un guardrail, y todos
    # devuelven lo mismo (una lista de hallazgos) ante la misma llamada.
    for gr in g.GUARDRAILS:
        assert isinstance(gr.revisar("", ""), list)


def test_el_reparto_actual_se_conserva():
    de_cv = {gr.nombre for gr in g.guardrails_para(g.CV)}
    de_carta = {gr.nombre for gr in g.guardrails_para(g.CARTA)}
    assert "cifras_no_respaldadas" in de_cv and "cifras_no_respaldadas" in de_carta
    assert "tecnologias_no_respaldadas" in de_cv and "tecnologias_no_respaldadas" in de_carta
    # skills lee lineas separadas por puntos: en prosa daria solo ruido
    assert "skills_no_respaldadas" in de_cv
    assert "skills_no_respaldadas" not in de_carta


def test_un_destino_desconocido_no_devuelve_nada():
    assert g.guardrails_para("inventado") == []


def test_revisar_devuelve_solo_los_que_encuentran_algo():
    master = "Vue.js - 8 anos. 166.000 usuarios."
    hallazgos = g.revisar("Experiencia con Django", master, g.CV)
    nombres = {h["regla"] for h in hallazgos}
    assert "tecnologias_no_respaldadas" in nombres
    for h in hallazgos:
        assert h["hallazgos"], "no se reporta un guardrail que no encontro nada"


def test_ANADIR_un_guardrail_no_toca_nada_mas(monkeypatch):
    """El test del principio abierto/cerrado: se registra y ya aparece."""
    class Inventado:
        nombre = "inventado_para_el_test"
        aplica_a = frozenset({g.CARTA})

        def revisar(self, texto, master):
            return ["hallazgo de prueba"] if "gato" in texto else []

    monkeypatch.setattr(g, "GUARDRAILS", list(g.GUARDRAILS) + [Inventado()])
    hallazgos = g.revisar("aqui hay un gato", "master vacio", g.CARTA)
    assert any(h["regla"] == "inventado_para_el_test" for h in hallazgos)
