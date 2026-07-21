"""Test: separación de responsabilidades PERFIL BASE / EXPERIENCIA / generador.

Principio de arquitectura (Vero, 21-jul-2026):
- El CV generado NO añade información nueva: solo reorganiza evidencia del Master.
- PERFIL BASE define identidad; NUNCA es evidencia ni fuente de contenido a copiar.
- La EXPERIENCIA (y proyectos/formación/skills) es la única evidencia.
- Jerarquía: la oferta decide qué enfatizar; el PERFIL BASE desde qué identidad;
  la experiencia qué se puede afirmar; el CV es reorganización de esa evidencia.

Valida el prompt real en cv_server_railway.py como texto (sin Flask/docx).
"""
import pathlib

FUENTE = pathlib.Path(__file__).with_name("cv_server_railway.py")


def run():
    src = FUENTE.read_text(encoding="utf-8")
    fallos = []

    # 1. El principio fundamental y la jerarquía de fuentes deben estar en el prompt.
    for marca in ("PRINCIPIO FUNDAMENTAL", "JERARQUÍA DE FUENTES"):
        if marca not in src:
            fallos.append(f"Falta el bloque '{marca}' en el prompt.")

    # 2. El resumen NO debe instruirse "desde el resumen del CV master" (riesgo de
    #    copiar el PERFIL BASE). Debe generarse desde la EXPERIENCIA.
    riesgo_copia = [
        "basados en el resumen del CV master",   # ES
        "based on the CV master summary",         # EN
    ]
    for frag in riesgo_copia:
        if frag in src:
            fallos.append(
                f"El resumen se instruye a partir de {frag!r}: riesgo de copiar el "
                "PERFIL BASE. Debe generarse desde la EXPERIENCIA real."
            )

    if fallos:
        print("FALLOS:\n- " + "\n- ".join(fallos))
        return 1
    print("OK - separación de fuentes explícita; el resumen se genera desde la EXPERIENCIA")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
