"""Test aislado de sanear_tipografia().

El modulo cv_server_railway importa Flask/docx en el nivel superior, que no estan
instalados en este entorno. Por eso extraemos SOLO la funcion sanear_tipografia
del fichero fuente y la ejecutamos en un namespace limpio (solo stdlib). Asi el
test valida el codigo REAL del fichero, sin arrastrar dependencias pesadas.

Regla NO NEGOCIABLE de la usuaria: ningun CV/carta puede salir con guiones largos
(—), guiones medios (–) ni flechas (→). Este test es la red de seguridad.
"""
import re
import pathlib

FUENTE = pathlib.Path(__file__).with_name("cv_server_railway.py")


def _cargar_sanear():
    texto = FUENTE.read_text(encoding="utf-8")
    # Extrae el bloque completo: constantes _ARROWS/_DASHES/_RE_* + la funcion,
    # desde `_ARROWS =` hasta justo antes de `def generar_docx`.
    m = re.search(r"\n_ARROWS = .*?(?=\ndef generar_docx\()", texto, re.S)
    if not m:
        raise AssertionError("No se encontro el bloque sanear_tipografia en cv_server_railway.py")
    ns = {}
    exec("import re\n" + m.group(0), ns)
    return ns["sanear_tipografia"]


def run():
    sanear = _cargar_sanear()

    casos = [
        # (entrada, idioma, esperado)
        ("CookYourWeb — Madrid", "es", "CookYourWeb - Madrid"),
        ("Bitcode Technology — Madrid", "es", "Bitcode Technology - Madrid"),
        ("2017 – 2025", "es", "2017 - 2025"),
        ("Inglés: C1 — educación bilingüe", "es", "Inglés: C1 - educación bilingüe"),
        ("INSA S.A. — Proyecto IBM — Bruselas / Madrid", "es",
         "INSA S.A. - Proyecto IBM - Bruselas / Madrid"),
        ("migración Vue.js → React + TypeScript", "es",
         "migración Vue.js a React + TypeScript"),
        ("ALD Automotive → Ayvens", "es", "ALD Automotive a Ayvens"),
        ("ALD Automotive → Ayvens", "en", "ALD Automotive to Ayvens"),
        # texto limpio no debe cambiar
        ("Node.js, Python, Flask, APIs REST", "es", "Node.js, Python, Flask, APIs REST"),
        ("- Logré reducir el tiempo de build", "es", "- Logré reducir el tiempo de build"),
        ("Full-Stack Developer | React | TypeScript", "es",
         "Full-Stack Developer | React | TypeScript"),
    ]

    fallos = []
    for entrada, idioma, esperado in casos:
        got = sanear(entrada, idioma)
        if got != esperado:
            fallos.append(f"  IN : {entrada!r}\n  EXP: {esperado!r}\n  GOT: {got!r}")

    # Invariante duro: NUNCA deben quedar estos caracteres en la salida
    prohibidos = ["—", "–", "―", "‒", "−", "→", "←", "⟶", "➜", "➔", "➡", "⇒"]
    for entrada, idioma, _ in casos:
        got = sanear(entrada, idioma)
        for ch in prohibidos:
            if ch in got:
                fallos.append(f"  Caracter prohibido {ch!r} presente en salida: {got!r}")

    # Robustez: None / vacio no deben romper
    for v in ("", None):
        try:
            sanear(v, "es")
        except Exception as e:  # noqa
            fallos.append(f"  sanear({v!r}) lanzo excepcion: {e}")

    if fallos:
        print("FALLOS:\n" + "\n\n".join(fallos))
        return 1
    print(f"OK — {len(casos)} casos + invariantes de caracteres prohibidos pasan")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
