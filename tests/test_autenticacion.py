"""TDD - modulo de autenticacion: verificar el token de Google SIN depender de Flask.

Logica pura, reutilizable por Flask y FastAPI. Los tests nunca llaman a Google:
las claves publicas se inyectan y los tokens se firman con claves RSA de prueba.
"""
import dataclasses

import pytest

import autenticacion
from autenticacion import ErrorDeAutenticacion, Identidad, NoInvitada, ProveedorNoDisponible


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
