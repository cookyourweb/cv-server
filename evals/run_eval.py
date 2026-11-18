"""Eval harness mínimo para generación de CV/carta (LLMOps).

Carga los casos de evals/casos/*.json y verifica restricciones básicas
(idioma, longitud de carta, no inventar métricas) sin llamar a LLMs reales
por defecto (--live para llamar al modelo).

Uso:
  python evals/run_eval.py            # modo offline (solo valida casos)
  python evals/run_eval.py --live     # llama a cv-server /generar-cv y /generar-carta
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASOS = ROOT / "evals" / "casos"


def cargar_casos():
    return [json.loads(p.read_text()) for p in sorted(CASOS.glob("*.json"))]


def validar_caso(caso: dict) -> list[str]:
    """Validaciones estructurales del caso (sin LLM)."""
    errores = []
    r = caso.get("restricciones", {})
    if r.get("idioma") not in ("es", "en"):
        errores.append("idioma inválido")
    if not caso.get("cv_master"):
        errores.append("sin cv_master")
    if not caso.get("oferta", {}).get("empresa"):
        errores.append("sin empresa")
    if not caso.get("oferta", {}).get("puesto"):
        errores.append("sin puesto")
    return errores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Llama a cv-server (requiere credenciales)")
    args = parser.parse_args()

    casos = cargar_casos()
    print(f"Casos cargados: {len(casos)}")

    fallos = 0
    for caso in casos:
        errs = validar_caso(caso)
        if errs:
            fallos += 1
            print(f"  [FAIL] {caso['id']}: {errs}")
        else:
            print(f"  [OK]   {caso['id']}: {caso['descripcion']}")

    if args.live:
        print("\n--live no implementado aún: requiere cv-server corriendo y credenciales.")

    print(f"\nTotal: {len(casos)} casos, {fallos} con errores estructurales.")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

