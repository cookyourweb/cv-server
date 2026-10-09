"""C2 - AES-256-GCM for stored CV masters: AAD binding, rotation, fail closed."""
import base64
import os

import pytest

import cifrado

U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"


def _clave(byte: int = 1) -> str:
    return base64.b64encode(bytes([byte]) * 32).decode()


@pytest.fixture(autouse=True)
def llavero(monkeypatch):
    monkeypatch.setenv("CV_CLAVES", f"1:{_clave(1)}")
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "1")


def test_round_trip():
    version, nonce, cifrado_ = cifrado.cifrar("Angular 8 años", U1, "es")
    assert cifrado.descifrar(version, nonce, cifrado_, U1, "es") == "Angular 8 años"


def test_row_shape_and_no_plaintext():
    version, nonce, cifrado_ = cifrado.cifrar("Angular 8 años", U1, "es")
    assert version == 1 and len(nonce) == 12 and isinstance(cifrado_, bytes)
    assert b"Angular" not in cifrado_


def test_nonce_is_random_per_call():
    a = cifrado.cifrar("x", U1, "es")
    b = cifrado.cifrar("x", U1, "es")
    assert a[1] != b[1] and a[2] != b[2]


@pytest.mark.parametrize("usuario,idioma", [(U2, "es"), (U1, "en")])
def test_aad_mismatch_fails(usuario, idioma):
    version, nonce, cifrado_ = cifrado.cifrar("secreto", U1, "es")
    with pytest.raises(cifrado.ErrorDeCifrado):
        cifrado.descifrar(version, nonce, cifrado_, usuario, idioma)


def test_old_key_version_still_decrypts(monkeypatch):
    version, nonce, cifrado_ = cifrado.cifrar("antiguo", U1, "es")
    monkeypatch.setenv("CV_CLAVES", f"1:{_clave(1)},2:{_clave(2)}")
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "2")
    assert cifrado.cifrar("nuevo", U1, "es")[0] == 2
    assert cifrado.descifrar(version, nonce, cifrado_, U1, "es") == "antiguo"


def test_recifrar_moves_a_row_to_the_active_key(monkeypatch):
    fila = cifrado.cifrar("antiguo", U1, "es")
    monkeypatch.setenv("CV_CLAVES", f"1:{_clave(1)},2:{_clave(2)}")
    monkeypatch.setenv("CV_CLAVE_ACTIVA", "2")
    nueva = cifrado.recifrar(*fila, U1, "es")
    assert nueva[0] == 2
    assert cifrado.descifrar(*nueva, U1, "es") == "antiguo"


def test_tampered_ciphertext_fails():
    version, nonce, cifrado_ = cifrado.cifrar("secreto", U1, "es")
    malo = bytes([cifrado_[0] ^ 1]) + cifrado_[1:]
    with pytest.raises(cifrado.ErrorDeCifrado):
        cifrado.descifrar(version, nonce, malo, U1, "es")


def test_tampered_nonce_fails():
    version, nonce, cifrado_ = cifrado.cifrar("secreto", U1, "es")
    with pytest.raises(cifrado.ErrorDeCifrado):
        cifrado.descifrar(version, bytes([nonce[0] ^ 1]) + nonce[1:], cifrado_, U1, "es")


def test_wrong_nonce_length_fails():
    version, nonce, cifrado_ = cifrado.cifrar("secreto", U1, "es")
    with pytest.raises(cifrado.ErrorDeCifrado):
        cifrado.descifrar(version, nonce[:8], cifrado_, U1, "es")


def test_unknown_key_version_fails():
    _, nonce, cifrado_ = cifrado.cifrar("secreto", U1, "es")
    with pytest.raises(cifrado.ErrorDeCifrado):
        cifrado.descifrar(9, nonce, cifrado_, U1, "es")


@pytest.mark.parametrize("claves,activa", [
    (None, "1"),                      # no keyring
    (f"1:{_clave(1)}", None),         # no active version
    (f"1:{_clave(1)}", "2"),          # active not in keyring
    ("1:no-es-base64!!", "1"),        # garbage
    (f"1:{base64.b64encode(b'corta').decode()}", "1"),  # not 32 bytes
    ("", "1"),
])
def test_missing_or_bad_key_config_fails_closed(monkeypatch, claves, activa):
    for nombre, valor in (("CV_CLAVES", claves), ("CV_CLAVE_ACTIVA", activa)):
        if valor is None:
            monkeypatch.delenv(nombre, raising=False)
        else:
            monkeypatch.setenv(nombre, valor)
    with pytest.raises(cifrado.ErrorDeCifrado):
        cifrado.cifrar("secreto", U1, "es")


def test_errors_never_contain_the_content():
    version, nonce, cifrado_ = cifrado.cifrar("CANARIO-SECRETO", U1, "es")
    with pytest.raises(cifrado.ErrorDeCifrado) as e:
        cifrado.descifrar(version, nonce, cifrado_, U2, "es")
    assert "CANARIO" not in str(e.value) and e.value.__cause__ is None
