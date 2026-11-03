import unittest.mock as mock

import pytest

import server
import base_de_datos


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        return self

    def scalar_one(self):
        return 3


class _FakeMotor:
    def connect(self):
        return _FakeConn()

    def begin(self):
        # The gate now commits through begin(); same fake connection.
        return _FakeConn()


@pytest.fixture()
def cliente():
    return server.app.test_client()


@mock.patch("byok.resolver_generacion_por_email")
def test_generar_cv_rechaza_sin_key_ni_trial(mock_resolver, cliente, monkeypatch):
    monkeypatch.setattr(server, "CLAVE_MAQUINA", "clave-test")
    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "motor", lambda: _FakeMotor())
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"nombre": "Demo"})
    mock_resolver.return_value = {
        "permitido": False,
        "motivo": "No puedes generar sin clave propia ni generaciones gratuitas.",
    }

    respuesta = cliente.post(
        "/generar-cv",
        headers={"X-Clave-Maquina": "clave-test"},
        json={"email": "a@b.com", "empresa": "Acme", "puesto": "Dev"},
    )

    assert respuesta.status_code == 403
    datos = respuesta.get_json()
    assert datos["ok"] is False


@mock.patch("byok.resolver_generacion_por_email")
def test_generar_cv_pasa_si_key(mock_resolver, cliente, monkeypatch):
    monkeypatch.setattr(server, "CLAVE_MAQUINA", "clave-test")
    monkeypatch.setattr(base_de_datos, "configurada", lambda: True)
    monkeypatch.setattr(base_de_datos, "motor", lambda: _FakeMotor())
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"nombre": "Demo"})
    mock_resolver.return_value = {
        "permitido": True,
        "modo": "key",
        "clave": "sk-test",
        "motivo": None,
    }

    respuesta = cliente.post(
        "/generar-cv",
        headers={"X-Clave-Maquina": "clave-test"},
        json={"email": "a@b.com", "empresa": "Acme", "puesto": "Dev"},
    )

    assert respuesta.status_code not in (403, 503)