"""Test: el CUERPO del CV también es data-driven, no code-driven (fase 2A).

Regla de arquitectura (Vero, 21-jul-2026): el Python es un MOTOR GENÉRICO.
No debe conocer identidades, títulos ni posicionamiento específicos de la
candidata. El posicionamiento por oferta se deriva del CV Master (bloques
"POSICIONAMIENTO" y "EVOLUCIÓN PROFESIONAL"), nunca de reglas hardcodeadas.

Valida el prompt real en cv_server_railway.py como texto (sin Flask/docx).
"""
import pathlib

FUENTE = pathlib.Path(__file__).with_name("cv_server_railway.py")


def run():
    src = FUENTE.read_text(encoding="utf-8")
    fallos = []

    # 1. El cuerpo NO debe hardcodear posicionamiento específico de la candidata.
    prohibidos = [
        "Senior Python Engineer",        # negativo hardcodeado (1293)
        "Oferta UX Engineer",            # posicionamiento por tipo hardcodeado (1292)
        "Background de 10+ años en frontend, UX",  # frase de resumen hardcodeada (1277)
        "Firebase, MongoDB e integraciones",       # stack específico hardcodeado (1290)
    ]
    for frag in prohibidos:
        if frag in src:
            fallos.append(
                f"Posicionamiento hardcodeado en el prompt: {frag!r}. "
                "Debe derivarse de POSICIONAMIENTO/EVOLUCIÓN del CV Master."
            )

    # 2. El prompt DEBE apoyarse en los bloques del Master para el posicionamiento.
    if "EVOLUCIÓN" not in src:
        fallos.append("El prompt no referencia el bloque 'EVOLUCIÓN PROFESIONAL' del CV Master.")
    if "POSICIONAMIENTO" not in src:
        fallos.append("El prompt no referencia el bloque 'POSICIONAMIENTO' del CV Master.")

    if fallos:
        print("FALLOS:\n- " + "\n- ".join(fallos))
        return 1
    print("OK - el cuerpo es data-driven (posicionamiento desde POSICIONAMIENTO/EVOLUCIÓN, sin hardcode)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
