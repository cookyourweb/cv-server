"""The match reads the caller's OWN profile row (real PostgreSQL, DATABASE_URL_PRUEBAS).

Notion and the master are faked; the profile goes in through PUT /perfil and comes out
through the match, scoped to the caller: Bea has no profile, so she gets the 409 that
Ana does not.
"""
import fuente_master
import notion
from fuente_master import MasterResuelto
# Fixtures of the sign-up route tests (database in test mode, throwaway key, invited people).
from test_rutas_alta import PERFIL, bd, cliente, migrado, par, personas  # noqa: F401

O1 = "11111111-1111-4111-8111-111111111111"
OFERTA = {"puesto": "Dev", "descripcion": "Angular, 10 years of experience", "tags": [], "idioma": "es"}


def _notion_falso(monkeypatch, master):
    monkeypatch.setattr(notion, "NOTION_DB_USUARIOS", "usuarios-de-prueba")
    monkeypatch.setattr(notion, "buscar_usuario_por_email", lambda email: {"notion_id": "bb" * 16})
    monkeypatch.setattr(notion, "leer_ofertas_de_usuaria", lambda ids, nid: {O1.replace("-", ""): OFERTA})
    monkeypatch.setattr(fuente_master, "resolver_master",
                        lambda usuario, idioma, email="": MasterResuelto(master, "", idioma, False))


def test_each_caller_is_matched_with_her_own_profile(bd, cliente, personas):
    _notion_falso(bd, "Angular desde 2015")
    assert cliente.put("/perfil", headers=personas["ana"].cabeceras, json=PERFIL).status_code == 200
    ana = cliente.get(f"/ofertas/{O1}/encaje", headers=personas["ana"].cabeceras)
    assert ana.status_code == 200
    # Her 12 years of profile experience cover the "10 years" the offer asks for.
    assert any("años de experiencia" in c["requisito"] for c in ana.get_json()["cubiertos"])
    bea = cliente.get(f"/ofertas/{O1}/encaje", headers=personas["bea"].cabeceras)
    assert bea.status_code == 200  # a master is enough...
    assert not any("años" in c["requisito"] for c in bea.get_json()["cubiertos"])  # ...but not her profile


def test_neither_profile_nor_master_is_409_for_a_real_user(bd, cliente, personas):
    _notion_falso(bd, "")
    r = cliente.get(f"/ofertas/{O1}/encaje", headers=personas["bea"].cabeceras)
    assert r.status_code == 409 and r.get_json()["motivo"] == "sin_perfil_ni_master"
