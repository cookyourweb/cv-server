import base64
import os

from cryptography.exceptions import InvalidTag
import pytest

from byok import ErrorDeCifrado, cifrar_api_key, descifrar_api_key, validar_api_key


def _clave_env(monkeypatch):
    raw = os.urandom(32)
    monkeypatch.setenv("BYOK_CLAVES", f"1:{base64.b64encode(raw).decode('ascii')}")
    monkeypatch.setenv("BYOK_CLAVE_ACTIVA", "1")


def test_cifrado_redondo(monkeypatch):
    _clave_env(monkeypatch)
    uid = "usuaria-123"
    version, nonce, cifrado = cifrar_api_key(uid, "anthropic", "sk-ant-secret")
    salida = descifrar_api_key(uid, "anthropic", version, nonce, cifrado)
    assert salida == "sk-ant-secret"


def test_descifrado_falla_con_usuario_distinto(monkeypatch):
    _clave_env(monkeypatch)
    version, nonce, cifrado = cifrar_api_key("uid-a", "anthropic", "sk-ant-secret")
    with pytest.raises(ErrorDeCifrado):
        descifrar_api_key("uid-b", "anthropic", version, nonce, cifrado)


def test_validacion_de_formato():
    assert validar_api_key("anthropic", "sk-ant-abc") is True
    assert validar_api_key("groq", "gsk_abc") is True
    assert validar_api_key("anthropic", "gsk_abc") is False
    assert validar_api_key("anthropic", "") is False