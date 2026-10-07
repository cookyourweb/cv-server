"""TDD - GET /yo: la usuaria se identifica con su token de Google.

Los tokens se firman con una clave RSA de prueba y las claves publicas se
inyectan: nunca se llama a Google. Se reutilizan los ayudantes de
test_autenticacion.
"""
import pytest
import rsa

import server as srv
from autenticacion import ClavesPublicas, ConfiguracionOIDC
from test_autenticacion import AUDIENCIA, EMISOR, Descargador, Reloj, _firmar, _jwks, _payload


@pytest.fixture(scope="module")
def par():
    return rsa.newkeys(1024)


def _preparar(monkeypatch, par, invitadas=("ana@ejemplo.es",), descarga=None):
    config = ConfiguracionOIDC(AUDIENCIA, (EMISOR,), "https://jwks", frozenset(invitadas))
    descarga = descarga or Descargador(_jwks(k1=par[0]))
    monkeypatch.setattr(srv, "CONFIG_OIDC", config)
    monkeypatch.setattr(srv, "CLAVES", ClavesPublicas("https://jwks", descarga, reloj=Reloj()))


@pytest.fixture
def cliente(monkeypatch, par):
    _preparar(monkeypatch, par)
    with srv.app.test_client() as c:
        yield c


def _bearer(par, **cambios):
    return {"Authorization": f"Bearer {_firmar(par[1], _payload(**cambios))}"}


def test_token_valido_de_invitada_responde_200_con_su_identidad(cliente, par):
    r = cliente.get("/yo", headers=_bearer(par))
    assert r.status_code == 200
    assert r.get_json() == {"sub": "42", "email": "ana@ejemplo.es", "nombre": "Ana"}


def test_sin_authorization_responde_401(cliente):
    assert cliente.get("/yo").status_code == 401


def test_token_invalido_responde_401(cliente):
    r = cliente.get("/yo", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401


def test_la_clave_de_maquina_no_sustituye_al_token(cliente, monkeypatch):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", "clave-de-prueba-larga-y-aleatoria")
    r = cliente.get("/yo", headers={"X-Clave-Maquina": "clave-de-prueba-larga-y-aleatoria"})
    assert r.status_code == 401


# --- 403 y 503 ---------------------------------------------------------------

def test_valida_pero_no_invitada_responde_403(monkeypatch, par):
    _preparar(monkeypatch, par, invitadas=("otra@ejemplo.es",))
    with srv.app.test_client() as c:
        r = c.get("/yo", headers=_bearer(par))
    assert r.status_code == 403
    assert "ana@ejemplo.es" not in r.get_data(as_text=True)


def test_configuracion_incompleta_responde_503(monkeypatch, par):
    _preparar(monkeypatch, par)
    monkeypatch.setattr(srv, "CONFIG_OIDC", ConfiguracionOIDC("", (), "", frozenset()))
    with srv.app.test_client() as c:
        assert c.get("/yo", headers=_bearer(par)).status_code == 503


def test_jwks_inalcanzable_sin_cache_responde_503_con_cuerpo_generico(monkeypatch, par):
    _preparar(monkeypatch, par, descarga=Descargador(OSError("conexion rechazada por jwks")))
    with srv.app.test_client() as c:
        r = c.get("/yo", headers=_bearer(par))
    assert r.status_code == 503
    assert "jwks" not in r.get_data(as_text=True).lower()
