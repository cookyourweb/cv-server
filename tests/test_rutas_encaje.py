"""GET /ofertas/{id}/encaje and POST /encajes (C13, ADR-009).

No database and no Notion: the user's Notion record, her offers, her profile and her
master are faked at the seams of `rutas_encaje`. What is under test is the contract:
401 without a token, ownership by the Notion "Usuario" relation with ONE 404 body for
"not mine / nobody's / does not exist", fail closed on Notion errors, 409 with neither
profile nor master, the cap of 50 ids, and no CV text beyond the short evidence snippets.
"""
import json

import pytest
import rsa

import drive
import fuente_master
import notion
import rutas_encaje
import server as srv
from autenticacion import ClavesPublicas, ConfiguracionOIDC
from fuente_master import MasterResuelto
from test_autenticacion import AUDIENCIA, EMISOR, Descargador, Reloj, _firmar, _jwks, _payload

_RESOLVER_REAL = fuente_master.resolver_master  # captured before any fixture replaces it
ELLA = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
O1 = "11111111-1111-4111-8111-111111111111"
O2 = "22222222-2222-4222-8222-222222222222"
O3 = "33333333-3333-4333-8333-333333333333"
CANARIO = "CANARIO-MASTER-7731 dirigi un equipo de nueve personas en una sede secreta"
LINEA_LARGA = "Python " + "x" * 400
MASTER = f"Desarrollo de servicios con Angular y TypeScript\nUsé Python a diario\n{CANARIO}\n{LINEA_LARGA}"
PERFIL = {"rol": "Frontend", "anios_experiencia": 12, "stack": ["Angular"], "idiomas": ["es"],
          "ubicacion": "Madrid", "modalidad": ["remoto"], "salario_min": 1, "salario_moneda": "EUR"}
OFERTA = {"puesto": "Frontend", "descripcion": "Buscamos Angular, TypeScript y Python.",
          "tags": [], "idioma": "es"}
NO_ENCONTRADO = {"ok": False, "error": "no encontrado"}
NO_DISPONIBLE = {"ok": False, "error": "servicio no disponible"}


@pytest.fixture(scope="module")
def par():
    return rsa.newkeys(1024)


@pytest.fixture
def mundo(monkeypatch, par):
    """A signed-in invited user with a Notion record, a profile, a master and two offers."""
    config = ConfiguracionOIDC(AUDIENCIA, (EMISOR,), "https://jwks", frozenset({"ana@ejemplo.es"}))
    monkeypatch.setattr(srv, "CONFIG_OIDC", config)
    monkeypatch.setattr(srv, "CLAVES", ClavesPublicas("https://jwks", Descargador(_jwks(k1=par[0])), reloj=Reloj()))
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda email: None)
    monkeypatch.setattr(notion, "NOTION_DB_USUARIOS", "usuarios-de-prueba")
    estado = {"consultas_usuario": [], "pedidos_ofertas": [], "perfil": dict(PERFIL),
              "ofertas": {}, "masters": [], "idiomas_master": []}

    def buscar(email):
        estado["consultas_usuario"].append(email)
        return {"notion_id": ELLA, "email": email}

    def ofertas(ids, notion_id):
        estado["pedidos_ofertas"].append((list(ids), notion_id))
        return {i.replace("-", ""): o for i, o in estado["ofertas"].items()
                if i.replace("-", "") in {x.replace("-", "") for x in ids}}

    def master(usuario, idioma, email=""):
        estado["idiomas_master"].append(idioma)
        return MasterResuelto(estado.get("master", MASTER), "", idioma, False)

    monkeypatch.setattr(notion, "buscar_usuario_por_email", buscar)
    monkeypatch.setattr(notion, "leer_ofertas_de_usuaria", ofertas)
    monkeypatch.setattr(fuente_master, "resolver_master", master)
    monkeypatch.setattr(rutas_encaje, "_perfil_de", lambda usuario_id: estado["perfil"])
    estado["ofertas"] = {O1: OFERTA}
    return estado


@pytest.fixture
def cliente(mundo):
    with srv.app.test_client() as c:
        yield c


@pytest.fixture
def cabeceras(par):
    return {"Authorization": f"Bearer {_firmar(par[1], _payload())}"}


# --- authentication ----------------------------------------------------------------------

def test_both_routes_exist():
    reglas = {(m, r.rule) for r in srv.app.url_map.iter_rules() for m in r.methods - {"HEAD", "OPTIONS"}}
    assert ("GET", "/ofertas/<oferta_id>/encaje") in reglas and ("POST", "/encajes") in reglas


def test_S6_12_no_token_is_401_and_nothing_is_looked_up(cliente, mundo):
    assert cliente.get(f"/ofertas/{O1}/encaje").status_code == 401
    assert cliente.post("/encajes", json={"ids": [O1]}).status_code == 401
    assert mundo["consultas_usuario"] == [] and mundo["pedidos_ofertas"] == []


def test_a_bad_token_and_the_machine_key_are_401(cliente, monkeypatch):
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", "clave-de-prueba-larga-y-aleatoria")
    for cab in ({"Authorization": "Bearer basura"}, {"X-Clave-Maquina": "clave-de-prueba-larga-y-aleatoria"}):
        assert cliente.get(f"/ofertas/{O1}/encaje", headers=cab).status_code == 401
        assert cliente.post("/encajes", json={"ids": [O1]}, headers=cab).status_code == 401


# --- GET /ofertas/{id}/encaje ------------------------------------------------------------

def test_the_owner_gets_the_match(cliente, cabeceras, mundo):
    r = cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert set(cuerpo) == {"cubiertos", "huecos", "no_evaluables", "alcanzable", "cobertura"}
    assert {c["requisito"] for c in cuerpo["cubiertos"]} >= {"Angular", "TypeScript", "Python"}
    assert cuerpo["alcanzable"] is True


def test_ownership_is_asked_with_the_callers_own_notion_page(cliente, cabeceras, mundo):
    cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert mundo["consultas_usuario"] == ["ana@ejemplo.es"]
    assert mundo["pedidos_ofertas"] == [([O1], ELLA)]


def test_the_offer_language_picks_the_master_language(cliente, cabeceras, mundo):
    mundo["ofertas"][O1] = {**OFERTA, "idioma": "en"}
    cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert mundo["idiomas_master"] == ["en"]


def test_REQ_6_5_the_master_never_appears_in_the_response(cliente, cabeceras, mundo):
    a = cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    b = cliente.post("/encajes", json={"ids": [O1]}, headers=cabeceras)
    for r in (a, b):
        texto = r.get_data(as_text=True)
        assert "CANARIO-MASTER-7731" not in texto and "sede secreta" not in texto
        assert LINEA_LARGA not in texto          # a long master line is cut to a short snippet
    assert "Desarrollo de servicios con Angular y TypeScript" in a.get_data(as_text=True)  # the GET carries short evidence: the test can fail
    assert "Desarrollo de servicios" not in b.get_data(as_text=True)  # the batch carries no evidence at all


@pytest.mark.parametrize("duenos_de_oferta", ["nadie", "otra", "no existe"])
def test_S6_12b_not_mine_nobodys_and_missing_are_one_identical_404(cliente, cabeceras, mundo, duenos_de_oferta):
    mundo["ofertas"] = {}  # the Notion layer answers "not hers" the same way in all three cases
    r = cliente.get(f"/ofertas/{O2}/encaje", headers=cabeceras)
    assert r.status_code == 404 and r.get_json() == NO_ENCONTRADO


def test_a_malformed_id_is_the_same_404(cliente, cabeceras, mundo):
    mundo["ofertas"] = {}
    r = cliente.get("/ofertas/no-es-un-id/encaje", headers=cabeceras)
    assert r.status_code == 404 and r.get_json() == NO_ENCONTRADO


def test_a_caller_without_a_notion_record_owns_nothing(cliente, cabeceras, mundo, monkeypatch):
    monkeypatch.setattr(notion, "buscar_usuario_por_email", lambda email: None)
    r = cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert r.status_code == 404 and r.get_json() == NO_ENCONTRADO
    assert mundo["pedidos_ofertas"] == []


def test_a_notion_record_without_page_id_owns_nothing(cliente, cabeceras, mundo, monkeypatch):
    monkeypatch.setattr(notion, "buscar_usuario_por_email", lambda email: {"notion_id": ""})
    r = cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert r.status_code == 404 and mundo["pedidos_ofertas"] == []


# --- fail closed ---------------------------------------------------------------------------

def _falla(excepcion):
    def _(*a, **k):
        raise excepcion
    return _


@pytest.mark.parametrize("sitio, excepcion", [
    ("leer_ofertas_de_usuaria", notion.ErrorDeNotion()),
    ("buscar_usuario_por_email", RuntimeError("detalle interno con ana@ejemplo.es")),
])
def test_a_notion_error_is_503_with_no_data_on_both_routes(cliente, cabeceras, monkeypatch, sitio, excepcion):
    monkeypatch.setattr(notion, sitio, _falla(excepcion))
    for r in (cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras),
              cliente.post("/encajes", json={"ids": [O1]}, headers=cabeceras)):
        assert r.status_code == 503 and r.get_json() == NO_DISPONIBLE
        assert "detalle" not in r.get_data(as_text=True)


def test_unconfigured_users_database_is_503_not_404(cliente, cabeceras, monkeypatch):
    monkeypatch.setattr(notion, "NOTION_DB_USUARIOS", "")
    monkeypatch.setattr(notion, "buscar_usuario_por_email", lambda email: None)
    r = cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert r.status_code == 503


def test_a_failing_master_source_is_503(cliente, cabeceras, monkeypatch):
    monkeypatch.setattr(fuente_master, "resolver_master", _falla(RuntimeError("drive roto")))
    r = cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert r.status_code == 503 and "drive" not in r.get_data(as_text=True)


def test_a_failing_profile_lookup_is_503(cliente, cabeceras, monkeypatch):
    monkeypatch.setattr(rutas_encaje, "_perfil_de", _falla(rutas_encaje.base_de_datos.ErrorDeBaseDeDatos()))
    assert cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras).status_code == 503


# --- profile and master --------------------------------------------------------------------

def test_neither_profile_nor_master_is_409(cliente, cabeceras, mundo):
    mundo["perfil"], mundo["master"] = None, ""
    for r in (cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras),
              cliente.post("/encajes", json={"ids": [O1]}, headers=cabeceras)):
        assert r.status_code == 409
        assert r.get_json() == {"ok": False, "error": "falta el perfil y el master", "motivo": "sin_perfil_ni_master"}


def test_a_master_without_profile_is_enough(cliente, cabeceras, mundo):
    mundo["perfil"] = None
    assert cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras).status_code == 200


def test_a_profile_without_master_is_enough_and_covers_nothing(cliente, cabeceras, mundo):
    mundo["master"] = ""
    r = cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert r.status_code == 200
    assert r.get_json()["cubiertos"] == [] and r.get_json()["alcanzable"] is False


def test_the_409_is_after_ownership_so_a_stranger_still_sees_a_404(cliente, cabeceras, mundo):
    mundo["perfil"], mundo["master"], mundo["ofertas"] = None, "", {}
    assert cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras).status_code == 404


def test_the_consent_gate_of_the_stored_master_is_respected(cliente, cabeceras, mundo, monkeypatch):
    """Through the REAL resolver: without enviar_cv_a_ia the Neon master is not read."""
    class Repo:
        usuario_id = "u"
        leidas = 0
        def tiene_consentimiento(self, tipo):
            return False
        def obtener_cv(self, idioma):
            Repo.leidas += 1
    monkeypatch.setattr(fuente_master, "resolver_master", _RESOLVER_REAL)
    monkeypatch.setattr(fuente_master, "base_para_email", lambda email: fuente_master.MasterEnBase(Repo()))
    monkeypatch.setattr(drive, "leer_cv_master_desde_drive", lambda usuario, idioma="es": drive.MasterCV("", ""))
    mundo["perfil"] = None
    r = cliente.get(f"/ofertas/{O1}/encaje", headers=cabeceras)
    assert r.status_code == 409 and Repo.leidas == 0



# --- POST /encajes -------------------------------------------------------------------------

def test_the_batch_returns_only_her_offers_and_never_reveals_the_rest(cliente, cabeceras, mundo):
    r = cliente.post("/encajes", json={"ids": [O1, O2, O3, "basura"]}, headers=cabeceras)
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert list(cuerpo) == [O1]
    assert cuerpo[O1]["alcanzable"] is True


def test_the_batch_is_keyed_by_the_id_exactly_as_sent(cliente, cabeceras, mundo):
    mundo["ofertas"] = {O1: OFERTA, O2: OFERTA, O3: OFERTA}
    r = cliente.post("/encajes", json={"ids": [O3, O1, O2]}, headers=cabeceras)
    assert set(r.get_json()) == {O1, O2, O3}


def test_the_same_offer_in_two_spellings_is_answered_once_under_the_first(cliente, cabeceras, mundo):
    plano = O1.replace("-", "")
    r = cliente.post("/encajes", json={"ids": [plano, O1]}, headers=cabeceras)
    assert list(r.get_json()) == [plano]


def test_50_ids_are_accepted_and_51_are_422(cliente, cabeceras, mundo):
    ids = [f"{n:032x}" for n in range(1, 52)]
    assert cliente.post("/encajes", json={"ids": ids[:50]}, headers=cabeceras).status_code == 200
    r = cliente.post("/encajes", json={"ids": ids}, headers=cabeceras)
    assert r.status_code == 422 and r.get_json() == {"ok": False, "error": "datos no validos", "campos": ["ids"]}
    assert len(mundo["pedidos_ofertas"]) == 1  # the 51 never reached Notion


@pytest.mark.parametrize("cuerpo", [None, [], {}, {"ids": "x"}, {"ids": [1]}, {"ids": [None]}, {"ids": {"a": 1}},
                                    {"ids": ["a" * 200]}])
def test_a_malformed_body_is_422(cliente, cabeceras, cuerpo):
    r = cliente.post("/encajes", json=cuerpo, headers=cabeceras)
    assert r.status_code == 422


def test_an_empty_list_is_an_empty_result_without_touching_the_master(cliente, cabeceras, mundo):
    r = cliente.post("/encajes", json={"ids": []}, headers=cabeceras)
    assert r.status_code == 200 and r.get_json() == {}
    assert mundo["idiomas_master"] == []


def test_the_master_is_read_once_per_language_not_once_per_offer(cliente, cabeceras, mundo):
    mundo["ofertas"] = {O1: OFERTA, O2: OFERTA, O3: {**OFERTA, "idioma": "en"}}
    cliente.post("/encajes", json={"ids": [O1, O2, O3]}, headers=cabeceras)
    assert sorted(mundo["idiomas_master"]) == ["en", "es"]


def test_the_response_is_plain_json_of_the_match_only(cliente, cabeceras, mundo):
    r = cliente.post("/encajes", json={"ids": [O1]}, headers=cabeceras)
    assert r.mimetype == "application/json"
    assert set(json.loads(r.data)[O1]) == {"alcanzable", "cobertura"}
