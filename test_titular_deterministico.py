"""TDD - el TITULAR lo construye el codigo, no el modelo.

Medido el 24jul2026: TRES formulaciones distintas de la regla del titular, TRES fallos
en produccion.

  1. Guardrail enumerando titulos prohibidos  -> se colo "Leader".
  2. Contrato PERFIL BASE con 'Orden del titular' explicito -> los dos CV usaron la
     'Variante permitida' sin cumplir su condicion.
  3. Contrato + detector -> ademas fusiono dos identidades en una ("A & B").

Y el contraste que lo explica: cambiar la PLANTILLA del formato de experiencia funciono
a la primera; cambiar una REGLA de comportamiento fallo tres veces.

    El titular tiene un contrato CERRADO. No hay ninguna razon para que lo escriba
    un LLM. Las identidades y su orden estan declarados y la unica libertad real son
    uno o dos modificadores: eso es rellenar un hueco, no generar.

Asi que se ensambla en codigo desde el PERFIL BASE. Al modelo se le sigue pidiendo la
linea HEADLINE, pero solo se aprovechan sus MODIFICADORES, y unicamente si el Master los
respalda. El fallo pasa de improbable a imposible.
"""
import cv_server_railway as srv

MASTER = """# PERFIL BASE

## Identidad profesional
Frontend Tech Lead | Full-Stack Developer | AI Engineer | React · TypeScript · Node.js | 10+ years in digital product

## Identidades permitidas
- Frontend Tech Lead
- Full-Stack Developer
- AI Engineer

## Roles objetivo
- Technical Training in Generative AI
- GenAI Adoption

EXPERIENCIA
Training developers on generative AI. Context Engineering and LLM integration.
React, TypeScript, Node.js, Python. Design systems and accessibility.
"""

BASE = ("Frontend Tech Lead | Full-Stack Developer | AI Engineer | "
        "React · TypeScript · Node.js | 10+ years in digital product")


def test_si_el_modelo_invierte_el_orden_se_corrige():
    """El fallo de Revolut: uso la Variante permitida sin cumplir la condicion."""
    malo = "AI Engineer | Full-Stack Developer | Frontend Tech Lead | LLM Systems"
    out = srv.construir_titular(malo, MASTER)
    assert out.startswith("Frontend Tech Lead | Full-Stack Developer | AI Engineer")


def test_si_el_modelo_fusiona_identidades_se_corrige():
    """El fallo de N-iX: 'AI Engineer & Full-Stack Developer' como un solo bloque."""
    malo = "AI Engineer & Full-Stack Developer | Frontend Tech Lead | React · TypeScript"
    out = srv.construir_titular(malo, MASTER)
    assert out.startswith("Frontend Tech Lead | Full-Stack Developer | AI Engineer")
    assert "&" not in out


def test_si_el_modelo_inventa_una_identidad_se_descarta():
    """'AI Engineering Leader' fue el titular del primer CV de N-iX."""
    malo = "AI Engineering Leader | Full-Stack Developer"
    out = srv.construir_titular(malo, MASTER)
    assert "Leader" not in out
    assert out.startswith("Frontend Tech Lead | Full-Stack Developer | AI Engineer")


def test_el_modificador_respaldado_por_el_master_se_acepta():
    """La unica libertad real del modelo, y se le respeta."""
    bueno = ("Frontend Tech Lead | Full-Stack Developer | AI Engineer | "
             "Context Engineering | 10+ years in digital product")
    out = srv.construir_titular(bueno, MASTER)
    assert "Context Engineering" in out
    assert "React" not in out, "El modificador propuesto sustituye al del PERFIL BASE"


def test_el_modificador_sin_respaldo_se_descarta():
    """'Engineering Productivity': 'Productivity' no aparece en ningun sitio del Master."""
    malo = ("Frontend Tech Lead | Full-Stack Developer | AI Engineer | "
            "Engineering Productivity | 10+ years in digital product")
    out = srv.construir_titular(malo, MASTER)
    assert "Productivity" not in out
    assert "React" in out, "Sin modificador valido se conserva el del PERFIL BASE"


def test_la_seniority_nunca_se_pierde():
    """El CV de N-iX se comio '10+ years' para meter posicionamiento en su hueco."""
    malo = ("AI Engineer | Full-Stack Developer | Frontend Tech Lead | "
            "React · TypeScript · Node.js | GenAI Adoption")
    out = srv.construir_titular(malo, MASTER)
    assert out.endswith("10+ years in digital product")


def test_como_mucho_dos_modificadores():
    malo = ("Frontend Tech Lead | Full-Stack Developer | AI Engineer | "
            "Context Engineering | GenAI Adoption | Technical Training | "
            "10+ years in digital product")
    out = srv.construir_titular(malo, MASTER)
    partes = [p.strip() for p in out.split("|")]
    # 3 identidades + como mucho 2 modificadores + seniority
    assert len(partes) <= 6


def test_el_titular_correcto_no_se_toca():
    assert srv.construir_titular(BASE, MASTER) == BASE


def test_sin_perfil_base_se_respeta_lo_que_diga_el_modelo():
    """Un Master antiguo sin contrato sigue funcionando como hasta ahora."""
    viejo = "EXPERIENCIA\nFrontend Tech Lead en Bitcode. React y TypeScript."
    t = "Lo Que El Modelo Quiera | React"
    assert srv.construir_titular(t, viejo) == t


def test_titular_vacio_devuelve_el_del_perfil_base():
    """Si el modelo no escribio HEADLINE, el contrato ya trae un titular valido."""
    assert srv.construir_titular("", MASTER) == BASE


def test_el_detector_ya_no_encuentra_nada_en_lo_construido():
    """El detector pasa a ser red de seguridad: sobre un titular construido, calla."""
    for malo in (
        "AI Engineer | Full-Stack Developer | Frontend Tech Lead | LLM Systems",
        "AI Engineer & Full-Stack Developer | Frontend Tech Lead",
        "AI Engineering Leader | Full-Stack Developer",
    ):
        construido = srv.construir_titular(malo, MASTER)
        assert srv.detectar_titular_fuera_de_contrato(construido, MASTER) == [], (
            f"El titular construido a partir de {malo!r} sigue disparando el detector"
        )
