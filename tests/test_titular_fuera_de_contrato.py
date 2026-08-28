"""TDD - detectar que el TITULAR generado se sale del contrato del PERFIL BASE.

Caso real, 24jul2026. Se desplegaron las reglas del titular ancla y se regeneraron los
CV de N-iX y Revolut. Los DOS salieron con:

    AI Engineer | Full-Stack Developer | Frontend Tech Lead | ...

que es el orden de "Variante permitida", cuya condicion declarada es "solo empresas cuyo
producto principal sea la IA (OpenAI, Anthropic, Cohere, Mistral, Hugging Face)". Ni N-iX
(outsourcing IT) ni Revolut (fintech) la cumplen. El modelo leyo el parentesis como
ejemplos y se autorizo la excepcion.

Es el mismo patron que dejo pasar "Leader" en el guardrail de seniority: una lista que el
modelo interpreta como abierta. La leccion medida ese dia:

    escribir la regla en el prompt es DISCIPLINA; solo un detector es MECANISMO.

De las seis reglas nuevas, la unica que atrapo su propio fallo sin depender de la
obediencia del modelo fue `detectar_tecnologias_no_respaldadas`, que es codigo. Este
detector convierte la regla del titular ancla en codigo tambien.

Igual que los otros guardrails, NO aborta: avisa en la respuesta de /generar-cv para que
la persona lo revise antes de enviar.
"""
import server as srv

MASTER = """# PERFIL BASE

## Identidad profesional
Frontend Tech Lead | Full-Stack Developer | AI Engineer | React · TypeScript · Node.js | 10+ years in digital product

## Identidades permitidas
- Frontend Tech Lead
- Full-Stack Developer
- AI Engineer

## Orden del titular
1. Frontend Tech Lead
2. Full-Stack Developer
3. AI Engineer
4. Stack principal
5. Seniority

## Variante permitida
AI Engineer | Full-Stack Developer | Frontend Tech Lead
Condición: solo empresas cuyo producto principal sea la IA (OpenAI, Anthropic, Cohere).

EXPERIENCIA
Frontend Tech Lead en Bitcode. React, TypeScript, Node.js.
"""


def test_titular_correcto_no_se_marca():
    t = ("Frontend Tech Lead | Full-Stack Developer | AI Engineer | "
         "React · TypeScript · Node.js | 10+ years in digital product")
    assert srv.detectar_titular_fuera_de_contrato(t, MASTER) == []


def test_sustituir_los_modificadores_esta_permitido():
    """La unica libertad del modelo: cambiar el stack por lo que valora la oferta."""
    t = ("Frontend Tech Lead | Full-Stack Developer | AI Engineer | "
         "LLM Systems · Context Engineering | 10+ years in digital product")
    assert srv.detectar_titular_fuera_de_contrato(t, MASTER) == []


def test_regresion_el_titular_del_cv_de_n_ix():
    """El fallo literal del 24jul2026: orden invertido sin cumplir la condicion."""
    t = ("AI Engineer | Full-Stack Developer | Frontend Tech Lead | "
         "React · TypeScript · Node.js | GenAI Adoption & Engineering Productivity")
    avisos = srv.detectar_titular_fuera_de_contrato(t, MASTER)
    assert avisos, "El orden invertido debe avisarse: es la Variante permitida sin justificar"
    assert any("orden" in a.lower() for a in avisos)


def test_el_aviso_menciona_la_variante_cuando_coincide_con_ella():
    """Si el orden coincide EXACTAMENTE con la variante, hay que decirlo.

    No se puede verificar por codigo si la empresa cumple la condicion, asi que el
    detector no decide: informa a la persona de que se ha usado la excepcion."""
    t = "AI Engineer | Full-Stack Developer | Frontend Tech Lead | LLM Systems"
    avisos = srv.detectar_titular_fuera_de_contrato(t, MASTER)
    assert any("variante" in a.lower() for a in avisos)


def test_identidad_que_no_esta_en_el_repertorio_se_marca():
    """'AI Engineering Leader' fue el titular inventado del primer CV de N-iX."""
    t = "AI Engineering Leader | Full-Stack Developer | GenAI Adoption"
    avisos = srv.detectar_titular_fuera_de_contrato(t, MASTER)
    assert any("AI Engineering Leader" in a for a in avisos)


def test_falta_una_identidad_del_titular_base():
    t = "Frontend Tech Lead | Full-Stack Developer | React · TypeScript"
    avisos = srv.detectar_titular_fuera_de_contrato(t, MASTER)
    assert avisos, "Omitir una identidad del titular base debe avisarse"


def test_sin_perfil_base_no_se_puede_verificar_y_no_avisa():
    """Mismo criterio que los otros detectores: sin fuente, no se inventan alertas."""
    master_viejo = "EXPERIENCIA\nFrontend Tech Lead en Bitcode. React y TypeScript."
    t = "Cualquier Cosa | Lo Que Sea"
    assert srv.detectar_titular_fuera_de_contrato(t, master_viejo) == []


def test_titular_vacio_no_revienta():
    assert srv.detectar_titular_fuera_de_contrato("", MASTER) == []


def test_la_comparacion_ignora_mayusculas_y_espacios():
    t = ("frontend tech lead |  Full-Stack Developer  | AI ENGINEER | "
         "React · TypeScript · Node.js | 10+ years in digital product")
    assert srv.detectar_titular_fuera_de_contrato(t, MASTER) == []


def test_separador_de_punto_medio_tambien_vale():
    """El prompt permite separar identidades con ' | ' o ' · '."""
    t = "Frontend Tech Lead · Full-Stack Developer · AI Engineer · LLM Systems"
    assert srv.detectar_titular_fuera_de_contrato(t, MASTER) == []
