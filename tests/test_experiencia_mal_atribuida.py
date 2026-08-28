"""TDD - los AÑOS de una tecnologia no se le pegan a otra.

Caso real (18ago2026, oferta de prueba del sistema). La CARTA generada dijo:

    "mas de ocho años construyendo y manteniendo el frontend de una plataforma
     global de renting B2C+B2B con React y TypeScript"

El Master dice `Vue.js | Experta - 8 años en Bitcode/Ayvens`. **Los ocho años
son de Vue.** React llego con la migracion que ella lidero.

Ninguno de los guardrails que ya existen puede verlo, y no por descuido:

- `detectar_tecnologias_no_respaldadas`: React ESTA en el Master. No hay
  invencion que marcar.
- `detectar_skills_no_respaldadas`: idem, y ademas solo mira lineas de skills.
- `detectar_cifras_no_respaldadas`: ignora los años a proposito ("son fechas,
  no metricas"), y encima el 8 esta respaldado en el Master.

O sea que las tres piezas dicen la verdad por separado y la frase miente al
juntarlas. Lo que falta comprobar no es si la tecnologia existe ni si el numero
existe, sino **si ese numero es de esa tecnologia**.

Es mas peligroso que una invencion: una tecnologia inventada se cae en la
primera pregunta y se ve venir. Ocho años de React que fueron de Vue se
sostienen hasta que el entrevistador pregunta por la epoca de las clases.
"""
import cv_server_railway as srv

MASTER = """PERFIL BASE
Frontend Tech Lead con 10+ años de experiencia.

| Tecnologia | Nivel |
|---|---|
| React | Experta |
| Vue.js | Experta - 8 años en Bitcode/Ayvens |
| TypeScript | Experta |
| Angular | Conocimiento |
"""

CARTA_REAL = """Estimados/as,

Me dirijo a vosotros para expresar mi interes en la posicion de Frontend
Engineer. Mi experiencia encaja directamente con lo que describis: mas de ocho
años construyendo y manteniendo el frontend de una plataforma global de renting
B2C+B2B con React y TypeScript, donde disene desde cero un design system propio.

Atentamente,
Veronica Serna Perez
"""


def test_marca_react_cuando_los_anios_son_de_vue():
    """El caso real del 18ago2026. Los 8 años son de Vue, no de React."""
    marcadas = srv.detectar_experiencia_mal_atribuida(CARTA_REAL, MASTER)
    assert any("React" in m for m in marcadas), (
        f"no marco React con los años de Vue. Devolvio: {marcadas}"
    )


def test_no_marca_cuando_los_anios_van_con_su_tecnologia():
    """Ocho años de Vue es verdad: no se toca."""
    carta = "Tengo ocho años de experiencia con Vue.js en Bitcode."
    assert srv.detectar_experiencia_mal_atribuida(carta, MASTER) == []


def test_acepta_la_cifra_en_digitos():
    """'8 años' y 'ocho años' son la misma afirmacion."""
    carta = "Llevo 8 años trabajando con React a diario."
    marcadas = srv.detectar_experiencia_mal_atribuida(carta, MASTER)
    assert any("React" in m for m in marcadas), f"devolvio: {marcadas}"


def test_sin_anios_no_hay_nada_que_marcar():
    """Nombrar tecnologias sin atribuirles años es legitimo."""
    carta = "Trabajo con React y TypeScript en proyectos en produccion."
    assert srv.detectar_experiencia_mal_atribuida(carta, MASTER) == []


def test_sin_master_no_alerta():
    """Misma convencion que los otros detectores: sin fuente, no se inventa."""
    assert srv.detectar_experiencia_mal_atribuida(CARTA_REAL, "") == []


# El Master REAL de Vero (linea 137) no es una tabla, es una lista en una sola
# linea. Este caso es el que desmonto la primera version del detector: leyendo por
# lineas, los 8 años de Vue se repartian entre las once tecnologias de la lista y
# React quedaba respaldado. El fixture inventado era mas limpio que la realidad.
MASTER_LISTA = """PERFIL BASE
Frontend Tech Lead con 10+ años de experiencia.

STACK
Vue.js (8 años), React, Angular, TypeScript, Node.js, Azure, Docker, CI/CD,
GraphQL, REST APIs, Jest, Bootstrap, Figma, Adobe XD
"""


def test_los_anios_son_del_nombre_que_tienen_al_lado_no_de_toda_la_lista():
    """Forma real del Master: `Vue.js (8 años), React, Angular, ...`"""
    carta = ("Mi experiencia: mas de ocho años construyendo el frontend de una "
             "plataforma de renting con React y TypeScript.")
    marcadas = srv.detectar_experiencia_mal_atribuida(carta, MASTER_LISTA)
    assert any("React" in m for m in marcadas), (
        f"los 8 años son de Vue.js, no de React. Devolvio: {marcadas}"
    )


def test_en_la_lista_real_vue_sigue_estando_respaldado():
    """La otra cara: con Vue no se marca nada, que es toda la gracia."""
    carta = "Llevo ocho años trabajando con Vue.js en plataformas de renting."
    assert srv.detectar_experiencia_mal_atribuida(carta, MASTER_LISTA) == []
