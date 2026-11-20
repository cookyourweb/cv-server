"""Turn a .env export (Render) into the payload of the `cv-server-env` secret.

    python3 -I infra/secrets/entorno.py names  <file.env>   # names only, safe to read
    python3 -I infra/secrets/entorno.py json   <file.env> | gcloud secrets versions add ...
    python3 -I infra/secrets/entorno.py envfile <file.env> > <0600 temp file>

Rules this enforces, so nobody has to remember them:
- Values NEVER reach a terminal: `json` and `envfile` refuse to write to a TTY,
  and error messages name variables or line numbers, never values.
- Outer matching quotes are stripped. Render's export quotes some values and
  `kubectl --from-env-file` keeps them literally, which broke DATABASE_URL once
  (ADR-012, incidents table).
- A duplicated name is an error, not a silent "last one wins".
- The required variables must be present and non-empty, and CORS must allow the panel.
"""

import json
import re
import sys

OBLIGATORIAS = (
    "DATABASE_URL",
    "CLAUDE_API_KEY",
    "GROQ_API_KEY",
    "NOTION_TOKEN",
    "CLAVE_MAQUINA",
    "OIDC_AUDIENCIA",
    "OIDC_EMISORES",
    "CORS_ORIGENES",
)
ORIGEN_PANEL = "https://empleo.cookyourwebai.es"
_LINEA = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _sin_comillas(valor):
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
        return valor[1:-1]
    return valor


def parse(texto):
    """Return {name: value}. Raises ValueError naming the line, never the value."""
    env = {}
    for numero, linea in enumerate(texto.splitlines(), start=1):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        m = _LINEA.match(limpia)
        if not m:
            raise ValueError(f"line {numero} is not NAME=value")
        nombre, valor = m.group(1), m.group(2)
        if nombre in env:
            raise ValueError(f"{nombre} appears more than once (line {numero})")
        env[nombre] = _sin_comillas(valor)
    return env


def problems(env):
    """Return human-readable problems, naming variables only."""
    found = [f"{n} is missing or empty" for n in OBLIGATORIAS if not env.get(n)]
    cors = env.get("CORS_ORIGENES", "")
    if cors and ORIGEN_PANEL not in cors:
        found.append(f"CORS_ORIGENES does not include {ORIGEN_PANEL}: the panel could not call the API")
    return found


def main(argv):
    if len(argv) != 2 or argv[0] not in ("names", "json", "envfile"):
        print(__doc__, file=sys.stderr)
        return 2
    orden, ruta = argv
    if orden in ("json", "envfile") and sys.stdout.isatty():
        print("Refusing to write secret values to a terminal. Pipe or redirect the output.", file=sys.stderr)
        return 2
    try:
        with open(ruta, encoding="utf-8") as f:
            env = parse(f.read())
    except (OSError, ValueError) as e:
        print(f"{ruta}: {e}", file=sys.stderr)
        return 1
    fallos = problems(env)
    if fallos:
        for p in fallos:
            print(f"- {p}", file=sys.stderr)
        return 1
    if orden == "names":
        print(f"{len(env)} variables:")
        for nombre in sorted(env):
            print(f"  {nombre}")
    elif orden == "json":
        sys.stdout.write(json.dumps(env, ensure_ascii=False))
    else:
        for nombre, valor in env.items():
            sys.stdout.write(f"{nombre}={valor}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
