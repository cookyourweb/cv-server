"""Test: el TITULAR (HEADLINE) del CV es data-driven, no code-driven.

Regla de arquitectura acordada con la usuaria (21-jul-2026):
- El codigo NUNCA conoce las identidades profesionales de la candidata.
- Las identidades se leen SIEMPRE del bloque "# PERFIL BASE" del CV Master.
- Nada de listas negras/blancas de titulos hardcodeadas en el prompt.

Este test valida el codigo REAL del prompt en cv_server_railway.py sin arrastrar
Flask/docx: solo lee el fichero como texto y comprueba invariantes de contenido.
"""
import pathlib

FUENTE = pathlib.Path(__file__).with_name("cv_server_railway.py")


def run():
    src = FUENTE.read_text(encoding="utf-8")
    fallos = []

    # 1. El prompt DEBE apoyarse en el bloque "PERFIL BASE" del CV Master
    #    como fuente de verdad de las identidades.
    if "PERFIL BASE" not in src:
        fallos.append(
            "El prompt no referencia el bloque 'PERFIL BASE' del CV Master "
            "(las identidades deben leerse de ahi, no del codigo)."
        )

    # 2. NO debe quedar hardcodeada la identidad-base con ejemplos de titulos
    #    concretos (viejo acoplamiento identidad<->codigo).
    prohibidos_hardcode = [
        "Full-Stack Developer | UX Engineer",   # ejemplo per-tipo viejo (1266)
        "AI Product Builder",                     # allow/blacklist de titulos IA (1268-1269)
        "AI Solutions Engineer",                  # idem
    ]
    for frag in prohibidos_hardcode:
        if frag in src:
            fallos.append(
                f"Identidad/titulo hardcodeado en el prompt: {frag!r}. "
                "Las identidades deben derivarse del PERFIL BASE del CV Master."
            )

    if fallos:
        print("FALLOS:\n- " + "\n- ".join(fallos))
        return 1
    print("OK - el titular es data-driven (lee PERFIL BASE, sin identidades hardcodeadas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
