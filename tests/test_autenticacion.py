"""TDD - modulo de autenticacion: verificar el token de Google SIN depender de Flask.

Logica pura, reutilizable por Flask y FastAPI. Los tests nunca llaman a Google:
las claves publicas se inyectan y los tokens se firman con claves RSA de prueba.
"""
import dataclasses

import pytest

import autenticacion
from autenticacion import ConfiguracionOIDC, ErrorDeAutenticacion, Identidad, NoInvitada, ProveedorNoDisponible


def test_una_identidad_es_inmutable():
    i = Identidad(emisor="e", sub="1", email="a@b.es", nombre="Ana")
    with pytest.raises(dataclasses.FrozenInstanceError):
        i.email = "otra@b.es"


def test_no_invitada_no_se_captura_como_error_de_autenticacion():
    # El servidor responde 401 a uno y 403 a otro: si NoInvitada heredara de
    # ErrorDeAutenticacion, un `except ErrorDeAutenticacion` la convertiria en 401.
    assert not issubclass(NoInvitada, ErrorDeAutenticacion)
    with pytest.raises(NoInvitada):
        try:
            raise NoInvitada("no esta en la lista")
        except ErrorDeAutenticacion:
            pytest.fail("NoInvitada no debe ser un 401")


def test_proveedor_no_disponible_es_distinto_de_los_otros_errores():
    assert not issubclass(ProveedorNoDisponible, ErrorDeAutenticacion)
    assert not issubclass(ProveedorNoDisponible, NoInvitada)


def test_el_modulo_no_importa_flask():
    fuente = autenticacion.__file__
    with open(fuente, encoding="utf-8") as f:
        assert "flask" not in f.read().lower()


# --- configuracion -----------------------------------------------------------

ENTORNO = {
    "OIDC_AUDIENCIA": "cliente-123",
    "OIDC_EMISORES": " emisor-a , emisor-b ,",
    "OIDC_URL_JWKS": "https://claves.ejemplo/jwks",
    "OIDC_INVITADAS": " Ana@Ejemplo.es, ,bea@ejemplo.es ",
}


def test_la_configuracion_se_lee_del_entorno_recortando_y_separando_por_comas():
    c = ConfiguracionOIDC.desde_entorno(ENTORNO)
    assert c.audiencia == "cliente-123"
    assert c.emisores == ("emisor-a", "emisor-b")
    assert c.url_jwks == "https://claves.ejemplo/jwks"
    assert c.invitadas == frozenset({"ana@ejemplo.es", "bea@ejemplo.es"})
    assert c.completa()


def test_sin_entorno_la_configuracion_esta_vacia_e_incompleta():
    c = ConfiguracionOIDC.desde_entorno({})
    assert c.invitadas == frozenset()
    assert not c.completa()


def test_desde_entorno_lee_el_entorno_real_si_no_se_le_pasa_uno(monkeypatch):
    monkeypatch.setenv("OIDC_AUDIENCIA", "real")
    assert ConfiguracionOIDC.desde_entorno().audiencia == "real"


@pytest.mark.parametrize("falta", ["OIDC_AUDIENCIA", "OIDC_EMISORES", "OIDC_URL_JWKS"])
def test_la_configuracion_es_incompleta_si_falta_audiencia_emisores_o_jwks(falta):
    c = ConfiguracionOIDC.desde_entorno({**ENTORNO, falta: "  "})
    assert not c.completa()


def test_las_invitadas_vacias_no_hacen_incompleta_la_configuracion():
    # Lista vacia = no invita a nadie (403), no es un fallo de configuracion (503).
    assert ConfiguracionOIDC.desde_entorno({**ENTORNO, "OIDC_INVITADAS": ""}).completa()
