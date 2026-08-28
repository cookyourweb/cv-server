"""Integracion ligera del camino de render del DOCX SIN necesitar python-docx.

Replica las CONDICIONES de rama del bucle de generar_docx_con_cabecera (deteccion
sobre `linea` cruda, render sobre `sanear_tipografia(linea)`) usando la funcion
REAL extraida del fichero, y lo alimenta con el texto del CV que salio MAL
(Digital Talent Agency). Verifica:
  1. Ningun run renderizado contiene guion largo/medio ni flecha.
  2. Las lineas de empresa (con —) se siguen detectando -> conservan la negrita.
"""
import re, pathlib

FUENTE = pathlib.Path(__file__).with_name("cv_server_railway.py")

def _cargar_sanear():
    texto = FUENTE.read_text(encoding="utf-8")
    m = re.search(r"\n_ARROWS = .*?(?=\ndef generar_docx\()", texto, re.S)
    ns = {}
    exec("import re\n" + m.group(0), ns)
    return ns["sanear_tipografia"]

CV = """HEADLINE: Full-Stack Developer | Node.js | React | TypeScript
PERFIL PROFESIONAL
Desarrollador Full-Stack con 10+ años construyendo aplicaciones.
EXPERIENCIA PROFESIONAL
CookYourWeb — Madrid
Tech Lead Full Stack & AI Engineer
2025 – Actualidad
- Liderazgo de la migración Vue.js → React + TypeScript.
Bitcode Technology — Madrid
Frontend Tech Lead
2017 – 2025
- Migración de marca ALD Automotive → Ayvens sin downtime.
IDIOMAS
Inglés: C1 — educación bilingüe y año en Holyoke, MA."""

SECCIONES = ["PERFIL PROFESIONAL", "EXPERIENCIA PROFESIONAL", "EXPERIENCIA",
             "HABILIDADES TÉCNICAS", "HABILIDADES", "FORMACIÓN", "IDIOMAS",
             "PROYECTOS", "CERTIFICACIONES", "COMPETENCIAS"]
PROHIBIDOS = "—–―‒−→←⟶⟹➜➔➡⇒"


def run():
    sanear = _cargar_sanear()
    fallos, empresas_detectadas = [], []

    for linea in CV.strip().split("\n"):
        linea = linea.strip()
        if not linea:
            continue
        limpia = linea.upper().strip()
        render = sanear(linea, "es")

        if any(limpia.startswith(s) for s in SECCIONES) and len(linea) < 50:
            run_text = render.upper()
        elif linea.startswith(("- ", "• ", "* ")):
            run_text = "• " + render[2:].strip()
        elif ("—" in linea or "–" in linea) and len(linea) < 100:
            run_text = render
            empresas_detectadas.append(run_text)   # rama negrita empresa/fecha
        elif re.search(r"(20\d{2}|19\d{2})", linea) and len(linea) < 60:
            run_text = render
        else:
            run_text = render

        for ch in PROHIBIDOS:
            if ch in run_text:
                fallos.append(f"Caracter prohibido {ch!r} en run: {run_text!r}")

    # Las 3 lineas con — (2 empresas + idiomas + fechas con –) deben caer en la
    # rama de deteccion, no perderse. Al menos las 2 empresas + la de idiomas.
    if not any("CookYourWeb" in e for e in empresas_detectadas):
        fallos.append("La linea de CookYourWeb ya NO se detecta como empresa (perderia negrita)")
    if not any("Bitcode" in e for e in empresas_detectadas):
        fallos.append("La linea de Bitcode ya NO se detecta como empresa (perderia negrita)")

    if fallos:
        print("FALLOS:")
        for f in fallos:
            print("  " + f)
        return 1
    print("OK — CV problematico renderiza SIN guiones largos ni flechas; empresas detectadas:")
    for e in empresas_detectadas:
        print("   [negrita] " + e)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
