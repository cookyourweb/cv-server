"""TDD - verificar UNA A UNA las skills que el CV declara, sin catalogo.

Caso real (11ago2026, oferta de Koinly): el CV generado colo en la linea de
skills "React 19 · Tailwind (v4) · Radix UI · Mantine" y "TanStack Query".
Nada de eso esta en el Master: es el stack de la OFERTA.

El guardrail que ya existia, `detectar_tecnologias_no_respaldadas`, no vio
ninguna. Funciona con un catalogo de 173 variantes dadas de alta a mano, y
ninguna de las cuatro estaba. No es un descuido del catalogo: lo que el modelo
copia son las tecnologias NUEVAS de cada oferta, que por definicion no estan
en una lista escrita antes de leerla. Una lista blanca no puede cubrir un
mundo abierto.

Aqui se invierte el sentido. La seccion de skills es una lista de
AFIRMACIONES separadas por puntos, y cada una tiene que estar respaldada por
el Master, venga la tecnologia de donde venga. El mundo cerrado pasa al lado
correcto: el de lo que el CV afirma.
"""
import server as srv

MASTER = """PERFIL BASE
Frontend Tech Lead con 10+ años de experiencia.

| Tecnologia | Nivel |
|---|---|
| React | Experta |
| Next.js | Experta - proyectos en produccion |
| Vue.js | Experta - 8 años en Bitcode/Ayvens |
| TypeScript | Experta |
| Vite | Uso actual |
| Tailwind | Proyectos actuales |
"""

CV = """VERONICA SERNA PEREZ
Frontend Tech Lead | React · TypeScript · Design Systems

PROFESSIONAL SUMMARY
Frontend Tech Lead with deep experience in React and TypeScript.

TECHNICAL SKILLS
Frontend: React · Next.js · Vite

EDUCATION
MSc in Mobile Applications
"""


def _cv_con_skills(linea):
    return CV.replace("Frontend: React · Next.js · Vite", linea)


def test_skills_respaldadas_por_el_master_no_se_marcan():
    assert srv.detectar_skills_no_respaldadas(CV, MASTER) == []


def test_skill_ausente_del_master_se_marca():
    cv = _cv_con_skills("Frontend: React · Mantine")
    assert "Mantine" in srv.detectar_skills_no_respaldadas(cv, MASTER)


def test_tecnologia_fuera_de_cualquier_catalogo_se_marca():
    # El fallo que disparo esto: Radix UI no estaba dado de alta en el catalogo,
    # asi que el guardrail anterior era CIEGO a el. Aqui no hace falta catalogo.
    cv = _cv_con_skills("Frontend: React · Radix UI")
    assert "Radix UI" in srv.detectar_skills_no_respaldadas(cv, MASTER)


def test_la_version_es_una_afirmacion_y_tambien_se_verifica():
    # El Master dice "Tailwind", sin version. Declarar "v4" es afirmar de mas.
    cv = _cv_con_skills("Frontend: Tailwind (v4)")
    assert "Tailwind (v4)" in srv.detectar_skills_no_respaldadas(cv, MASTER)


def test_version_pegada_al_nombre_se_marca():
    # "React 19" no es "React": el Master no respalda la version.
    cv = _cv_con_skills("Frontend: React 19")
    assert "React 19" in srv.detectar_skills_no_respaldadas(cv, MASTER)


def test_calificador_de_nivel_no_es_una_afirmacion_tecnica():
    # "(strict)" describe COMO se usa TypeScript, no una herramienta aparte.
    cv = _cv_con_skills("Frontend: TypeScript (strict)")
    assert srv.detectar_skills_no_respaldadas(cv, MASTER) == []


def test_lo_que_va_entre_parentesis_tambien_se_verifica():
    # Pinia es una herramienta escondida dentro del parentesis de otra.
    cv = _cv_con_skills("Frontend: Vue.js (Composition API, Pinia)")
    marcadas = srv.detectar_skills_no_respaldadas(cv, MASTER)
    assert "Vue.js (Composition API, Pinia)" in marcadas


def test_solo_se_analiza_la_seccion_de_skills():
    # La cabecera y el resumen tambien llevan puntos separadores, pero no son
    # listas de skills: analizarlos llenaria el aviso de ruido.
    assert "Design Systems" not in srv.detectar_skills_no_respaldadas(CV, MASTER)


def test_la_etiqueta_de_la_linea_no_se_verifica():
    # "Frontend:" es el nombre del grupo, no una tecnologia declarada.
    assert "Frontend" not in srv.detectar_skills_no_respaldadas(CV, MASTER)


def test_mayusculas_y_espacios_no_cambian_el_resultado():
    cv = _cv_con_skills("Frontend:   NEXT.JS   ·  react ")
    assert srv.detectar_skills_no_respaldadas(cv, MASTER) == []


def test_seccion_de_skills_en_español_tambien_se_analiza():
    cv = CV.replace("TECHNICAL SKILLS", "COMPETENCIAS TECNICAS")
    cv = cv.replace("Frontend: React · Next.js · Vite", "Frontend: React · Mantine")
    assert "Mantine" in srv.detectar_skills_no_respaldadas(cv, MASTER)


def test_sin_master_no_se_puede_verificar_y_no_se_marca_nada():
    # Sin fuente de verdad no hay nada contra lo que contrastar.
    cv = _cv_con_skills("Frontend: Radix UI · Mantine")
    assert srv.detectar_skills_no_respaldadas(cv, "") == []


def test_cv_sin_seccion_de_skills_no_marca_nada():
    cv = CV.replace("TECHNICAL SKILLS\nFrontend: React · Next.js · Vite\n", "")
    assert srv.detectar_skills_no_respaldadas(cv, MASTER) == []


def test_cada_skill_se_reporta_una_sola_vez():
    cv = _cv_con_skills("Frontend: Mantine\nTooling: Mantine")
    assert srv.detectar_skills_no_respaldadas(cv, MASTER).count("Mantine") == 1
