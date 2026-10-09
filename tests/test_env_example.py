"""TDD - .env.example documenta las variables de identidad y CORS, sin valores."""
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
VARIABLES = ["OIDC_AUDIENCIA", "OIDC_EMISORES", "OIDC_JWKS_URL", "INVITADAS", "CORS_ORIGENES",
             "CV_CLAVES", "CV_CLAVE_ACTIVA"]


def _asignaciones():
    lineas = (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines()
    return dict(l.split("=", 1) for l in lineas if "=" in l and not l.startswith("#"))


@pytest.mark.parametrize("nombre", VARIABLES)
def test_la_variable_esta_documentada_y_vacia(nombre):
    asignaciones = _asignaciones()
    assert nombre in asignaciones
    assert asignaciones[nombre].strip() == ""


def test_se_explica_que_la_audiencia_no_es_la_de_drive():
    antes = (RAIZ / ".env.example").read_text(encoding="utf-8").split("OIDC_AUDIENCIA=")[0]
    comentario = "\n".join(antes.splitlines()[-3:])
    assert "PANEL" in comentario and "GOOGLE_CLIENT_ID" in comentario
