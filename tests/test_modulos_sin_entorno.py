"""TDD - los modulos tienen que importarse SIN credenciales en el entorno.

Hoy no se puede: `llm.py`, `notion.py` y `drive.py` hacen `os.environ["CLAVE"]`
a nivel de modulo, o sea AL IMPORTARSE. Consecuencias medibles:

1. `conftest.py` tiene que inyectar credenciales falsas para que la suite pueda
   siquiera importar el codigo. Un test que necesita mentir sobre el entorno
   antes de empezar esta probando el entorno, no el codigo.
2. Nadie puede abrir el repositorio, importar `guardrails` y leer que hace sin
   montarse primero un `.env`.

Lo que se busca: que la configuracion se lea, pero que su AUSENCIA no impida
importar. La validacion se hace al arrancar el servidor, donde importa, y
reportando TODAS las que falten de una vez en vez de la primera.

Es la version practica de la inversion de dependencias: el modulo deja de exigir
un entorno concreto para poder existir.
"""
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

MODULOS = ["guardrails", "docx_render", "llm", "notion", "drive", "real_jobs"]


def _importar_sin_entorno(modulos):
    """Importa en un proceso limpio, sin heredar NADA del entorno actual."""
    return subprocess.run(
        [sys.executable, "-c", f"import {', '.join(modulos)}"],
        cwd=RAIZ,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
        capture_output=True,
        text=True,
    )


def test_los_modulos_se_importan_sin_ninguna_credencial():
    r = _importar_sin_entorno(MODULOS)
    assert r.returncode == 0, f"no se pudieron importar sin entorno:\n{r.stderr[-600:]}"


def test_ningun_modulo_usa_os_environ_con_corchetes():
    # `os.environ["X"]` revienta al importar. `os.getenv("X", "")` no.
    for nombre in MODULOS:
        fuente = (RAIZ / f"{nombre}.py").read_text(encoding="utf-8")
        assert 'os.environ[' not in fuente, f"{nombre}.py exige la variable al importarse"


def test_el_servidor_avisa_de_TODAS_las_credenciales_que_faltan():
    import server

    faltan = server.credenciales_que_faltan({})
    assert "GROQ_API_KEY" in faltan
    assert "NOTION_TOKEN" in faltan
    assert len(faltan) >= 4, "tiene que reportarlas todas, no solo la primera"


def test_si_estan_todas_no_se_queja():
    import server

    entorno = {c: "valor" for c in server.CREDENCIALES_REQUERIDAS}
    assert server.credenciales_que_faltan(entorno) == []
