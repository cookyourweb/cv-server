import unittest.mock as mock
import pytest

import server


@pytest.fixture()
def cliente():
    return server.app.test_client()


@mock.patch("byok.resolver_generacion_por_email")
@mock.patch("server.call_llm_invitada")
def test_generar_cv_usa_key_propia(mock_llm, mock_resolver, cliente, monkeypatch):
    monkeypatch.setattr(server, "CLAVE_MAQUINA", "clave-test")
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"nombre": "Test", "email": email})
    from types import SimpleNamespace
    monkeypatch.setattr(server, "_resolver_master", lambda usuario, idioma, email: SimpleNamespace(texto="CV master"))
    monkeypatch.setattr(server, "_tiene_algun_master", lambda usuario: True)

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            return self

        def scalar_one(self):
            return 3

    monkeypatch.setattr("base_de_datos.configurada", lambda: True)
    monkeypatch.setattr("base_de_datos.motor", lambda: type("M", (), {"begin": lambda self: _FakeConn()})())
    monkeypatch.setattr("cuota.es_exenta", lambda email: True)
    monkeypatch.setattr("cuota.generar", lambda email, tipo, prompt, *, modelo, max_tokens, llamar, llamar_invitada=None, ahora=None: llamar_invitada() if llamar_invitada else llamar())

    mock_resolver.return_value = {
        "permitido": True,
        "modo": "key",
        "clave": "sk-ant-test-key",
        "motivo": None,
    }
    mock_llm.return_value = "ok"

    r = cliente.post(
        "/generar-cv",
        headers={"X-Clave-Maquina": "clave-test"},
        json={"email": "a@b.com", "empresa": "Acme", "puesto": "Dev"},
    )

    # The gate does not block. The LLM call receives the user's key.
    assert r.status_code != 403
    assert mock_llm.called
    kwargs = mock_llm.call_args.kwargs
    assert kwargs.get("api_key") == "sk-ant-test-key"


@mock.patch("byok.resolver_generacion_por_email")
@mock.patch("server.call_llm_invitada")
def test_generar_cv_trial_pasa_api_key_none(mock_llm, mock_resolver, cliente, monkeypatch):
    monkeypatch.setattr(server, "CLAVE_MAQUINA", "clave-test")
    monkeypatch.setattr(server, "buscar_usuario_por_email", lambda email: {"nombre": "Test", "email": email})
    from types import SimpleNamespace
    monkeypatch.setattr(server, "_resolver_master", lambda usuario, idioma, email: SimpleNamespace(texto="CV master"))
    monkeypatch.setattr(server, "_tiene_algun_master", lambda usuario: True)

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            return self

        def scalar_one(self):
            return 3

    monkeypatch.setattr("base_de_datos.configurada", lambda: True)
    monkeypatch.setattr("base_de_datos.motor", lambda: type("M", (), {"begin": lambda self: _FakeConn()})())
    monkeypatch.setattr("cuota.es_exenta", lambda email: True)
    monkeypatch.setattr("cuota.generar", lambda email, tipo, prompt, *, modelo, max_tokens, llamar, llamar_invitada=None, ahora=None: llamar_invitada() if llamar_invitada else llamar())

    mock_resolver.return_value = {
        "permitido": True,
        "modo": "trial",
        "clave": None,
        "motivo": None,
    }
    mock_llm.return_value = "ok"

    r = cliente.post(
        "/generar-cv",
        headers={"X-Clave-Maquina": "clave-test"},
        json={"email": "a@b.com", "empresa": "Acme", "puesto": "Dev"},
    )

    assert r.status_code != 403
    assert mock_llm.called
    kwargs = mock_llm.call_args.kwargs
    assert kwargs.get("api_key") is None