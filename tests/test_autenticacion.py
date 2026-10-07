"""TDD - modulo de autenticacion: verificar el token de Google SIN depender de Flask.

Logica pura, reutilizable por Flask y FastAPI. Los tests nunca llaman a Google:
las claves publicas se inyectan y los tokens se firman con claves RSA de prueba.
"""
import base64
import dataclasses
import json
import threading
import time

import pytest
import rsa
from google.auth import crypt, jwt

import autenticacion
from autenticacion import (
    ClavesPublicas,
    ConfiguracionOIDC,
    ErrorDeAutenticacion,
    Identidad,
    NoInvitada,
    ProveedorNoDisponible,
    verificar_token,
)


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


# --- claves publicas (JWKS) --------------------------------------------------

@pytest.fixture(scope="module")
def par_a():
    return rsa.newkeys(1024)


@pytest.fixture(scope="module")
def par_b():
    return rsa.newkeys(1024)


def _b64(numero: int) -> str:
    crudo = numero.to_bytes((numero.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


def _jwks(**claves):
    """claves: kid -> clave publica rsa."""
    return {"keys": [{"kty": "RSA", "kid": k, "n": _b64(p.n), "e": _b64(p.e)} for k, p in claves.items()]}


class Reloj:
    def __init__(self):
        self.ahora = 1000.0

    def __call__(self):
        return self.ahora


class Descargador:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def __call__(self, url):
        self.llamadas.append(url)
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        return r


def test_pem_de_devuelve_la_clave_del_kid_en_formato_pem(par_a):
    pub, _ = par_a
    d = Descargador(_jwks(k1=pub))
    pem = ClavesPublicas("https://jwks", d, reloj=Reloj()).pem_de("k1")
    assert rsa.PublicKey.load_pkcs1(pem.encode()) == pub
    assert d.llamadas == ["https://jwks"]


def test_dentro_del_ttl_no_vuelve_a_descargar(par_a):
    reloj, d = Reloj(), Descargador(_jwks(k1=par_a[0]))
    claves = ClavesPublicas("u", d, ttl=3600, reloj=reloj)
    claves.pem_de("k1")
    reloj.ahora += 3599
    claves.pem_de("k1")
    assert len(d.llamadas) == 1


def test_pasado_el_ttl_vuelve_a_descargar(par_a):
    reloj, d = Reloj(), Descargador(_jwks(k1=par_a[0]))
    claves = ClavesPublicas("u", d, ttl=3600, reloj=reloj)
    claves.pem_de("k1")
    reloj.ahora += 3601
    claves.pem_de("k1")
    assert len(d.llamadas) == 2


def test_kid_desconocido_refresca_una_vez_y_no_mas_de_una_cada_300_segundos(par_a, par_b):
    reloj = Reloj()
    d = Descargador(_jwks(k1=par_a[0]), _jwks(k1=par_a[0], k2=par_b[0]))
    claves = ClavesPublicas("u", d, reloj=reloj)
    claves.pem_de("k1")
    assert claves.pem_de("zzz") is None            # dentro de 300 s: no refresca
    assert len(d.llamadas) == 1
    reloj.ahora += 301
    assert claves.pem_de("k2") is not None         # rotacion: refresca y la encuentra
    assert len(d.llamadas) == 2
    assert claves.pem_de("zzz") is None            # otra desconocida: no refresca otra vez
    assert len(d.llamadas) == 2


def test_sin_cache_y_con_la_descarga_caida_es_proveedor_no_disponible():
    d = Descargador(OSError("sin red"))
    with pytest.raises(ProveedorNoDisponible):
        ClavesPublicas("u", d, reloj=Reloj()).pem_de("k1")


def test_con_cache_valida_y_descarga_caida_sirve_la_cache(par_a):
    reloj = Reloj()
    d = Descargador(_jwks(k1=par_a[0]), OSError("sin red"))
    claves = ClavesPublicas("u", d, ttl=3600, reloj=reloj)
    claves.pem_de("k1")
    reloj.ahora += 4000
    assert claves.pem_de("k1") is not None


def test_una_respuesta_sin_claves_validas_es_proveedor_no_disponible():
    with pytest.raises(ProveedorNoDisponible):
        ClavesPublicas("u", Descargador({"basura": 1}), reloj=Reloj()).pem_de("k1")


def test_con_hilos_concurrentes_se_descarga_una_sola_vez(par_a):
    d = Descargador(_jwks(k1=par_a[0]))
    original = d.__call__

    def lenta(url):
        time.sleep(0.05)
        return original(url)

    claves = ClavesPublicas("u", lenta, reloj=Reloj())
    hilos = [threading.Thread(target=claves.pem_de, args=("k1",)) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(d.llamadas) == 1


# --- verificar_token ---------------------------------------------------------

EMISOR = "https://emisor.ejemplo"
AUDIENCIA = "cliente-123"
CONFIG = ConfiguracionOIDC(AUDIENCIA, (EMISOR, "otro-emisor"), "https://jwks", frozenset())


def _payload(**cambios):
    ahora = int(time.time())
    base = {"iss": EMISOR, "aud": AUDIENCIA, "sub": "42", "email": "ana@ejemplo.es",
            "email_verified": True, "name": "Ana", "iat": ahora, "exp": ahora + 600}
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not None}


def _firmar(privada, payload, kid="k1"):
    firmante = crypt.RSASigner.from_string(privada.save_pkcs1().decode(), kid)
    return jwt.encode(firmante, payload, header={"kid": kid}).decode()


def _a_mano(header, payload, firma=b"firma"):
    def trozo(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{trozo(header)}.{trozo(payload)}.{base64.urlsafe_b64encode(firma).rstrip(b'=').decode()}"


@pytest.fixture
def claves(par_a):
    return ClavesPublicas("https://jwks", Descargador(_jwks(k1=par_a[0])), reloj=Reloj())


def test_un_token_valido_devuelve_la_identidad(par_a, claves):
    token = _firmar(par_a[1], _payload())
    assert verificar_token(token, CONFIG, claves) == Identidad(EMISOR, "42", "ana@ejemplo.es", "Ana")


def test_el_nombre_ausente_queda_vacio(par_a, claves):
    token = _firmar(par_a[1], _payload(name=None))
    assert verificar_token(token, CONFIG, claves).nombre == ""


def test_firmado_con_otra_clave_y_el_mismo_kid_se_rechaza(par_b, claves):
    token = _firmar(par_b[1], _payload(), kid="k1")
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(token, CONFIG, claves)


@pytest.mark.parametrize("alg", ["HS256", "none", "RS512"])
def test_algoritmos_distintos_de_rs256_se_rechazan(alg, claves):
    token = _a_mano({"alg": alg, "kid": "k1", "typ": "JWT"}, _payload())
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(token, CONFIG, claves)


def test_audiencia_incorrecta(par_a, claves):
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(_firmar(par_a[1], _payload(aud="ajeno")), CONFIG, claves)


def test_caducado_mas_alla_de_60_segundos_se_rechaza(par_a, claves):
    ahora = int(time.time())
    token = _firmar(par_a[1], _payload(iat=ahora - 900, exp=ahora - 120))
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(token, CONFIG, claves)


def test_caducado_dentro_de_los_60_segundos_de_margen_se_acepta(par_a, claves):
    ahora = int(time.time())
    token = _firmar(par_a[1], _payload(iat=ahora - 900, exp=ahora - 30))
    assert verificar_token(token, CONFIG, claves).email == "ana@ejemplo.es"


def test_emisor_fuera_de_la_lista(par_a, claves):
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(_firmar(par_a[1], _payload(iss="https://falso")), CONFIG, claves)


@pytest.mark.parametrize("valor", [False, None, "true", 1])
def test_email_verified_tiene_que_ser_el_booleano_true(valor, par_a, claves):
    token = _firmar(par_a[1], _payload(email_verified=valor))
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(token, CONFIG, claves)


def test_sin_email_se_rechaza(par_a, claves):
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(_firmar(par_a[1], _payload(email=None)), CONFIG, claves)


def test_kid_desconocido(par_a, claves):
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(_firmar(par_a[1], _payload(), kid="otro"), CONFIG, claves)


@pytest.mark.parametrize("token", ["", "basura", "a.b", "a.b.c", "....", "x" * 50])
def test_un_token_mal_formado_se_rechaza(token, claves):
    with pytest.raises(ErrorDeAutenticacion):
        verificar_token(token, CONFIG, claves)
