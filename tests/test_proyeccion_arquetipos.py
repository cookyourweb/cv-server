"""TDD - el CV es una PROYECCION de la misma trayectoria, no una identidad nueva.

Reglas formuladas por la usuaria el 24-jul-2026, despues de revisar el CV generado
para N-iX ("Gen AI Adoption Lead (Engineering Productivity)"). El CV salio vendiendo
Context Engineering, guardrails y JSON contracts a una oferta cuyo problema real era
que 1.700 desarrolladores adoptaran IA en su trabajo diario.

Cuatro fallos concretos de aquel CV, cada uno cubierto por un test de este fichero:

1. Titular "AI Engineering Leader" — identidad que NO esta en el Master (dice
   "Full-Stack Developer & AI Engineer"). El guardrail de seniority enumeraba
   palabras (Principal, Staff, Head, Director, Architect, Manager, Lead) y "Leader"
   no estaba en la lista. Las reglas deben enunciar PRINCIPIOS, no listas cerradas.
2. "IA" era un unico bucket. Una oferta de adopcion de GenAI y una de construccion
   de sistemas LLM piden CV distintos aunque las dos digan "IA".
3. "Proven track record ... measurable team productivity gains" y "measuring adoption
   impact": EFECTOS declarados sin evidencia en el Master. Se escribe el HECHO.
4. Jest / React Testing Library / CI-CD atribuidos al puesto de Bitcode, cuando el
   Master solo los lista en HABILIDADES sin ligarlos a ese puesto.

Igual que test_headline_datadriven.py, esto valida el codigo REAL del prompt leyendo
el fichero como texto: no arrastra Flask/docx ni llama a ningun LLM.
"""
import pathlib
import re

FUENTE = pathlib.Path(__file__).resolve().parent.parent / "cv_server_railway.py"
SRC = FUENTE.read_text(encoding="utf-8")


def test_regla_maestra_de_proyeccion():
    """La regla de mas alto nivel: proyeccion de la misma trayectoria, no identidad nueva.

    De ella se derivan casi todas las demas, asi que tiene que estar escrita explicita.
    """
    assert re.search(r"PROYECCI[OÓ]N", SRC, re.IGNORECASE), (
        "Falta la REGLA MAESTRA de proyeccion en el prompt. La adaptacion debe producir "
        "una proyeccion distinta de la MISMA trayectoria, nunca una identidad nueva."
    )
    assert re.search(r"nueva identidad profesional", SRC, re.IGNORECASE), (
        "La regla maestra debe prohibir explicitamente crear una identidad profesional nueva."
    )


def test_titular_base_es_ancla_estable():
    """El titular no se reinventa por oferta: es el ancla de identidad, alineada con LinkedIn."""
    assert "TITULAR BASE" in SRC, (
        "El prompt no declara el concepto 'Titular base'. Sin ancla, el titular deriva en "
        "cada oferta (AI Engineering Leader / GenAI Adoption Lead / Solutions Architect...) "
        "y parece que la candidata se reinventa para cada empresa."
    )
    # El orden de las identidades es branding: no se reordena.
    assert re.search(r"orden.{0,80}(no se altera|no se toca|NO reordenes|no se reordena)",
                     SRC, re.IGNORECASE | re.DOTALL), (
        "Falta la regla de que el ORDEN de las identidades del titular base no se altera."
    )


def test_titular_base_sigue_siendo_data_driven():
    """El ancla vive en el CV Master, NUNCA hardcodeada en el codigo.

    Complementa test_headline_datadriven.py: al anadir el titular base habria sido facil
    escribir el titular real de Veronica dentro del prompt. Eso reintroduce el
    acoplamiento identidad<->codigo que se elimino el 21-jul-2026.
    """
    prohibidos = [
        "Frontend Tech Lead | Full-Stack Developer | AI Engineer",
        "AI Engineer & Full-Stack Developer",
        "AI Engineering Leader",
        "producto digital",
    ]
    for frag in prohibidos:
        assert frag not in SRC, (
            f"Titular concreto hardcodeado en el codigo: {frag!r}. El titular base se "
            "declara en el PERFIL BASE del CV Master, nunca en el prompt."
        )


def test_identidad_y_posicionamiento_estan_separados():
    """La distincion que cierra el modelo mental (Vero, 24-jul-2026).

    IDENTIDAD  = quien ES la candidata. Cerrada, declarada en el PERFIL BASE.
                 Frontend Tech Lead, Full-Stack Developer, AI Engineer.
    POSICIONAMIENTO = como se PRESENTA esa misma trayectoria ante esta oferta.
                 Variable, derivado del arquetipo. GenAI Adoption, Context Engineering,
                 Applied AI, AI Automation...

    Sin nombrar la diferencia, "GenAI Adoption" es ambiguo: parece una identidad nueva
    (prohibida) cuando en realidad es un posicionamiento (permitido, si el Master lo
    respalda). El prompt tiene que decirlo, no dejarlo implicito.
    """
    assert re.search(r"IDENTIDAD.{0,60}POSICIONAMIENTO", SRC, re.IGNORECASE | re.DOTALL), (
        "El prompt no distingue explicitamente IDENTIDAD de POSICIONAMIENTO. Sin esa "
        "separacion el modelo no sabe si un posicionamiento cabe en el titular."
    )
    assert re.search(r"identidad(es)?.{0,120}(cerrad[ao])", SRC, re.IGNORECASE | re.DOTALL), (
        "Debe quedar dicho que el repertorio de IDENTIDADES es CERRADO."
    )
    assert re.search(r"posicionamiento.{0,200}no es una identidad", SRC, re.IGNORECASE | re.DOTALL), (
        "Debe quedar dicho que un posicionamiento NO es una identidad nueva: es la misma "
        "trayectoria presentada de otra forma."
    )


def test_el_posicionamiento_tambien_necesita_respaldo_del_master():
    """Un posicionamiento sin evidencia es una identidad inventada con otro nombre.

    Es la puerta por la que se colaria "GenAI Adoption" hoy, que el Master no respalda.
    """
    assert re.search(r"posicionamiento.{0,300}(respald|evidencia)", SRC, re.IGNORECASE | re.DOTALL), (
        "El posicionamiento debe exigir respaldo del Master igual que todo lo demas."
    )


def test_el_prompt_lee_el_contrato_del_perfil_base():
    """El PERFIL BASE es un CONTRATO de datos: el prompt no deduce nada, lo lee.

    Estructura acordada con la usuaria el 24-jul-2026. Cada seccion responde a una
    pregunta que antes el modelo tenia que interpretar, y al interpretar inventaba.
    """
    secciones = [
        "Identidad profesional",   # el titular base completo
        "Identidades permitidas",  # repertorio CERRADO
        "Orden del titular",       # el orden es dato, no criterio del modelo
        "Variante permitida",      # la unica excepcion, con su condicion
        "Nunca permitido",         # restricciones declaradas por el propio Master
    ]
    faltan = [s for s in secciones if s not in SRC]
    assert not faltan, (
        f"El prompt no lee estas secciones del PERFIL BASE: {faltan}. Si el prompt no "
        "las lee, el modelo vuelve a deducir la identidad, y deducir es lo que producia "
        "'AI Engineering Leader'."
    )


def test_no_queda_la_instruccion_contradictoria_de_reordenar():
    """REGRESION: el prompt decia a la vez 'REORDENA las identidades' y 'el orden no se altera'.

    Dos instrucciones opuestas en el mismo bloque dejan la decision al azar del modelo,
    que es justo lo que la regla del titular base viene a eliminar.
    """
    assert not re.search(r"REORDENA las identidades", SRC, re.IGNORECASE), (
        "Queda la instruccion de REORDENAR identidades, que contradice la regla del "
        "titular base (el orden es branding y no se altera)."
    )
    assert not re.search(r"cambia el [ÉE]NFASIS y el ORDEN", SRC, re.IGNORECASE), (
        "Queda 'cambia el ENFASIS y el ORDEN' aplicado al titular: contradice el ancla."
    )


def test_seniority_es_un_principio_no_una_lista_cerrada():
    """'Leader' se colo porque la regla enumeraba palabras en vez de enunciar el principio.

    Manana sera Champion, Evangelist, Authority o Distinguished. Una lista cerrada
    siempre va por detras.
    """
    assert re.search(r"NIVEL JER[AÁ]RQUICO", SRC, re.IGNORECASE), (
        "El guardrail de seniority debe enunciarse como principio ('no incrementar el "
        "nivel jerarquico'), no como enumeracion de titulos prohibidos."
    )
    assert re.search(r"(lista (no )?(es )?cerrada|no exhaustiva|sin (que la lista sea|caracter) )",
                     SRC, re.IGNORECASE), (
        "Los ejemplos de titulos prohibidos deben marcarse como lista ABIERTA; si no, el "
        "modelo la lee como exhaustiva y cuela cualquier termino que no aparezca."
    )
    # El termino que se colo de verdad en el CV de N-iX.
    assert "Leader" in SRC, "'Leader' debe figurar entre los ejemplos: es el caso real que fallo."


def test_ia_no_es_un_unico_arquetipo():
    """Cinco arquetipos de IA. 'IA es IA' fue exactamente el fallo con N-iX."""
    assert "ARQUETIPO" in SRC.upper(), "Falta el bloque de ARQUETIPO DE LA OFERTA en el prompt."
    arquetipos_ia = [
        "AI Engineer",
        "GenAI Adoption",
        "AI Solutions Architect",
        "AI Product Engineer",
        "AI Automation Engineer",
    ]
    faltan = [a for a in arquetipos_ia if a not in SRC]
    assert not faltan, (
        f"Arquetipos de IA sin distinguir en el prompt: {faltan}. Una oferta de adopcion "
        "de GenAI y una de construccion de sistemas LLM NO piden el mismo CV."
    )


def test_se_adapta_al_problema_de_la_empresa_no_al_producto_propio():
    """La regla que resume el arreglo de N-iX."""
    assert re.search(r"problema que (resuelve|tiene)", SRC, re.IGNORECASE), (
        "Falta la regla de adaptar al PROBLEMA que resuelve la empresa que contrata, "
        "no al producto que la candidata construyo."
    )


def test_hechos_no_efectos():
    """No declarar el efecto sin evidencia: escribir el hecho y dejar que se deduzca."""
    assert re.search(r"HECHOS,? NO EFECTOS", SRC, re.IGNORECASE), (
        "Falta la regla 'hechos, no efectos'."
    )
    # Vocabulario de resultado no medido que se colo en el CV de N-iX.
    for termino in ("proven track record", "measurable"):
        assert termino in SRC.lower(), (
            f"El prompt deberia prohibir explicitamente {termino!r}: aparecio en el CV de "
            "N-iX sin ningun dato en el Master que lo respaldase."
        )


def test_no_mover_skills_a_experiencia():
    """Jest/RTL/CI-CD estaban en HABILIDADES del Master, no en el puesto de Bitcode.

    El modelo los subio a un bullet de experiencia. La tecnologia es real, pero la
    ATRIBUCION es inventada, y el detector de tecnologias no lo ve porque solo compara
    presencia, no a que puesto se asigna.
    """
    assert re.search(r"NO MUEVAS SKILLS A EXPERIENCIA", SRC, re.IGNORECASE), (
        "Falta la regla que impide atribuir a un puesto concreto una tecnologia que el "
        "Master solo lista en HABILIDADES."
    )


def test_resumen_mayoritariamente_estable():
    """El resumen no se reescribe desde cero: ~70-80% estable, 20-30% adaptado."""
    assert re.search(r"RESUMEN.{0,120}ESTABILIDAD", SRC, re.IGNORECASE | re.DOTALL), (
        "Falta la regla de estabilidad del resumen."
    )
    assert re.search(r"70\s*-\s*80\s*%", SRC), (
        "La regla de estabilidad del resumen debe fijar la proporcion (70-80% estable)."
    )
