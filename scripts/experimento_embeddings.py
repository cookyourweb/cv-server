"""Experimento: ordenar ofertas por parecido con mi perfil usando embeddings.

NO es parte del servidor. Es un script para aprender cómo funcionan los
embeddings antes de meterlos en producción.

Qué hace, paso a paso:
  1. Lee ofertas de la base "Ofertas de Trabajo" de Notion.
  2. Convierte cada oferta, y mi perfil, en un embedding (una lista de números)
     llamando a la API de Gemini.
  3. Compara cada oferta con mi perfil con la similitud del coseno.
  4. Imprime el ranking y los posibles duplicados.

Uso (desde cv-server/):
  .venv/bin/python scripts/experimento_embeddings.py
  .venv/bin/python scripts/experimento_embeddings.py --perfil mi_perfil.txt
  .venv/bin/python scripts/experimento_embeddings.py --estados Pendiente "Enviado a empresa"
"""
import argparse
import math
import os
from pathlib import Path

import requests

# ─── Configuración ──────────────────────────────────────────────────────────

RAIZ = Path(__file__).resolve().parent.parent


def cargar_env() -> None:
    """Lee cv-server/.env sin depender de librerías extra."""
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linea in env.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def _credencial(nombre: str) -> str:
    """Se lee al usarla, no al importar: así los tests no necesitan claves."""
    valor = os.getenv(nombre, "")
    if not valor:
        raise SystemExit(f"Falta {nombre} en cv-server/.env")
    return valor


DB_OFERTAS = os.getenv("NOTION_DB_OFERTAS") or "33d11515f4b281efa776d0ea698b748f"
MODELO = "gemini-embedding-001"

# Perfil por defecto: solo cosas confirmadas, sin inflar.
# Mejor aún: pasá tu propio texto con --perfil.
PERFIL_POR_DEFECTO = """
Ingeniera frontend con más de 10 años de experiencia, ahora full stack con IA.
Frontend: React, TypeScript, Angular, Vue, Next.js, design systems, accesibilidad.
Durante 8 años responsable del frontend de mi proyecto en una plataforma de renting
de coches B2C y B2B (Bitcode Technology), integrando APIs REST con backend.
Backend e IA desde 2025: Python, FastAPI, Pydantic, TDD, arquitectura hexagonal, ADRs.
cv-server: servicio en producción que genera CVs adaptados a cada oferta con LLMs,
guardrails de veracidad y fallback entre proveedores (Groq, Gemini, Claude).
Automatizaciones con n8n, Notion como capa de datos, Postgres (Neon), Render, Vercel.
Tu Vuelta al Sol: SaaS en producción con la API de OpenAI.
Autónoma. Prefiero remoto; híbrido solo en Madrid.
"""

# Lo que NO quiero. El score final resta el parecido con este texto, para que
# bajen las ofertas muy tech pero de otra especialidad.
ANTIPERFIL_POR_DEFECTO = """
Backend puro en Java, Spring Boot, Go, .NET o Ruby, con 5+ años de backend.
Investigación en machine learning: entrenar modelos, PyTorch, TensorFlow, MLOps, visión 3D.
Data engineering: Spark, Snowflake, pipelines de datos, BigQuery.
Principal o Staff de plataforma e infraestructura: Kubernetes, Terraform, Kafka a escala.
Anotación de datos o evaluación de modelos por horas. Presencial fuera de Madrid.
"""

# ─── 1. Leer ofertas de Notion ──────────────────────────────────────────────


def _texto(prop: dict) -> str:
    """Saca el texto plano de una propiedad de Notion (title o rich_text)."""
    if not prop:
        return ""
    trozos = prop.get("title") or prop.get("rich_text") or []
    return "".join(t.get("plain_text", "") for t in trozos)


def leer_ofertas(estados: list[str]) -> list[dict]:
    filtro = {"or": [{"property": "Estado", "select": {"equals": e}} for e in estados]}
    headers = {
        "Authorization": f"Bearer {_credencial('NOTION_TOKEN')}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    ofertas, cursor = [], None
    while True:
        cuerpo = {"filter": filtro, "page_size": 100}
        if cursor:
            cuerpo["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{DB_OFERTAS}/query",
                          headers=headers, json=cuerpo, timeout=30)
        r.raise_for_status()
        datos = r.json()
        for pagina in datos["results"]:
            p = pagina["properties"]
            empresa = _texto(p.get("Empresa"))
            puesto = _texto(p.get("Puesto"))
            # El texto que convertimos en embedding: cuanto más contexto, mejor.
            texto = f"{puesto} en {empresa}. {_texto(p.get('Descripción'))} {_texto(p.get('Notas'))}"
            ofertas.append({"empresa": empresa, "puesto": puesto,
                            "estado": (p.get("Estado") or {}).get("select", {}).get("name", ""),
                            "texto": texto[:2000]})
        if not datos.get("has_more"):
            return ofertas
        cursor = datos["next_cursor"]

# ─── 2. Texto → embedding (lista de números) ────────────────────────────────


def embeddings(textos: list[str]) -> list[list[float]]:
    """Una sola llamada a Gemini convierte hasta 100 textos en vectores."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:batchEmbedContents"
    clave = _credencial("GEMINI_API_KEY")
    vectores = []
    for i in range(0, len(textos), 100):
        lote = textos[i:i + 100]
        cuerpo = {"requests": [{"model": f"models/{MODELO}",
                                "content": {"parts": [{"text": t}]},
                                "taskType": "SEMANTIC_SIMILARITY"} for t in lote]}
        r = requests.post(url, headers={"x-goog-api-key": clave},
                          json=cuerpo, timeout=60)
        r.raise_for_status()
        vectores += [e["values"] for e in r.json()["embeddings"]]
    return vectores

# ─── 3. Comparar: similitud del coseno ──────────────────────────────────────


def coseno(a: list[float], b: list[float]) -> float:
    """1.0 = mismo significado, 0 = nada que ver.

    Mide el ángulo entre las dos flechas: si apuntan hacia el mismo lado,
    los textos hablan de lo mismo. Esto es lo que pgvector hace con `<=>`.
    """
    punto = sum(x * y for x, y in zip(a, b))
    return punto / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def puntuar(ofertas: list[dict], v_perfil: list[float], v_anti: list[float],
            v_ofertas: list[list[float]]) -> list[dict]:
    """Devuelve copias de las ofertas con su score, de mejor a peor.

    score = parecido con lo que quiero - parecido con lo que evito.
    """
    puntuadas = []
    for o, v in zip(ofertas, v_ofertas):
        quiero, evito = coseno(v_perfil, v), coseno(v_anti, v)
        puntuadas.append({**o, "quiero": quiero, "evito": evito, "score": quiero - evito})
    return sorted(puntuadas, key=lambda o: o["score"], reverse=True)


def duplicados(ofertas: list[dict], v_ofertas: list[list[float]],
               umbral: float = 0.95) -> list[tuple[dict, dict, float]]:
    """Pares de ofertas casi idénticas: probablemente la misma publicada dos veces."""
    pares = []
    for i in range(len(ofertas)):
        for j in range(i + 1, len(ofertas)):
            s = coseno(v_ofertas[i], v_ofertas[j])
            if s > umbral:
                pares.append((ofertas[i], ofertas[j], s))
    return pares

# ─── 4. Resultado ───────────────────────────────────────────────────────────


def main() -> None:
    cargar_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--perfil", help="fichero de texto con tu perfil")
    ap.add_argument("--estados", nargs="+", default=["Pendiente"])
    args = ap.parse_args()

    perfil = Path(args.perfil).read_text() if args.perfil else PERFIL_POR_DEFECTO
    ofertas = leer_ofertas(args.estados)
    print(f"{len(ofertas)} ofertas leídas de Notion ({', '.join(args.estados)})\n")
    if not ofertas:
        return

    # Perfil y antiperfil van primero en la lista; el resto son las ofertas.
    vectores = embeddings([perfil, ANTIPERFIL_POR_DEFECTO] + [o["texto"] for o in ofertas])
    v_perfil, v_anti, v_ofertas = vectores[0], vectores[1], vectores[2:]
    print(f"Cada texto se convirtió en {len(v_perfil)} números.\n")

    print("RANKING  score = quiero - evito  (mejor arriba)")
    print("-" * 80)
    for o in puntuar(ofertas, v_perfil, v_anti, v_ofertas):
        print(f"{o['score']:+.3f}  (q {o['quiero']:.2f} / e {o['evito']:.2f})  "
              f"{o['empresa'][:24]:<24}  {o['puesto'][:38]}")

    print("\nPOSIBLES DUPLICADOS (similitud > 0.95 entre ofertas)")
    print("-" * 80)
    pares = duplicados(ofertas, v_ofertas)
    for a, b, s in pares:
        print(f"{s:.3f}  {a['empresa'][:25]} / {a['puesto'][:30]}"
              f"  ≈  {b['empresa'][:25]} / {b['puesto'][:30]}")
    if not pares:
        print("Ninguno.")


if __name__ == "__main__":
    main()
