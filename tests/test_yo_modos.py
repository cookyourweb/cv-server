"""GET /yo and the invitation source in both rollout modes.

Legacy mode: DATABASE_URL is not set (production today). The INVITADAS list decides and
no database is touched. Database mode: DATABASE_URL is set and the `invitaciones` table
decides; INVITADAS only works as an explicit bootstrap fallback.

Neither the database nor Notion nor Google is called: the user lookup is replaced where
it lives, and tokens are signed with a throwaway key.
"""
import logging
import uuid

import pytest
import rsa
from flask import g, jsonify

import base_de_datos
import server as srv
import usuarias
from autenticacion import ClavesPublicas, ConfiguracionOIDC
from test_autenticacion import AUDIENCIA, EMISOR, Descargador, Reloj, _firmar, _jwks, _payload

UID = uuid.uuid4()


@pytest.fixture(scope="module")
def par():
    return rsa.newkeys(1024)


def _config(invitadas=("ana@ejemplo.es",)):
    return ConfiguracionOIDC(AUDIENCIA, (EMISOR,), "https://jwks", frozenset(invitadas))


@pytest.fixture
def ctx(monkeypatch, par):
    """Server wired with a throwaway key; Notion finds nobody unless a test says so."""
    monkeypatch.setattr(srv, "CONFIG_OIDC", _config())
    monkeypatch.setattr(srv, "CLAVES", ClavesPublicas("https://jwks", Descargador(_jwks(k1=par[0])), reloj=Reloj()))
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda email: None)
    return monkeypatch


def _yo(par, **cambios):
    with srv.app.test_client() as c:
        return c.get("/yo", headers={"Authorization": f"Bearer {_firmar(par[1], _payload(**cambios))}"})


def _vero_con_master(ctx):
    ctx.setattr(srv, "buscar_usuario_por_email", lambda email: {"cv_master_file_id": "abc123"})


def _modo_bd(ctx, *, resolver=lambda identidad, **kw: UID, perfil=False, master=False):
    ctx.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    ctx.setattr(usuarias, "resolver_o_crear", resolver)
    ctx.setattr(usuarias, "tiene_perfil", lambda uid, conexion=None: perfil)
    ctx.setattr(usuarias, "tiene_master", lambda uid, conexion=None: master)


# --- legacy mode: no database --------------------------------------------------------

@pytest.fixture
def modo_heredado(ctx):
    def prohibido(*args, **kwargs):
        raise AssertionError("legacy mode must not touch the database")
    ctx.setattr(base_de_datos, "motor", prohibido)
    ctx.setattr(usuarias, "resolver_o_crear", prohibido)
    ctx.setattr(usuarias, "tiene_perfil", prohibido)
    ctx.setattr(usuarias, "tiene_master", prohibido)
    return ctx


def test_legacy_mode_admits_the_listed_email_without_a_database(modo_heredado, par):
    assert _yo(par).status_code == 200


def test_legacy_mode_denies_an_unlisted_email(modo_heredado, par):
    assert _yo(par, email="intrusa@ejemplo.es").status_code == 403


def test_legacy_mode_reports_a_drive_master_as_a_profile(modo_heredado, par):
    _vero_con_master(modo_heredado)
    cuerpo = _yo(par).get_json()
    assert cuerpo["tiene_perfil"] is True and cuerpo["origen_master"] == "drive"
    assert cuerpo["email"] == "ana@ejemplo.es"


def test_legacy_mode_never_says_false_because_sign_up_cannot_work_without_a_database(modo_heredado, par):
    cuerpo = _yo(par).get_json()
    assert "tiene_perfil" not in cuerpo and cuerpo["origen_master"] is None


def test_a_notion_failure_does_not_break_the_answer(modo_heredado, par):
    def cae(email):
        raise ConnectionError("notion down")
    modo_heredado.setattr(srv, "buscar_usuario_por_email", cae)
    r = _yo(par)
    assert r.status_code == 200 and "tiene_perfil" not in r.get_json()


def test_health_never_touches_the_database(ctx):
    def prohibido(*args, **kwargs):
        raise AssertionError("/health must not touch the database")
    ctx.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    ctx.setattr(base_de_datos, "motor", prohibido)
    ctx.setattr(usuarias, "resolver_o_crear", prohibido)
    with srv.app.test_client() as c:
        assert c.get("/health").status_code == 200


# --- database mode ---------------------------------------------------------------------

def test_the_table_decides_even_when_the_env_list_is_empty(ctx, par):
    ctx.setattr(srv, "CONFIG_OIDC", _config(invitadas=()))
    _modo_bd(ctx)
    assert _yo(par).status_code == 200


def test_the_table_wins_over_the_env_list(ctx, par):
    _modo_bd(ctx, resolver=lambda identidad, **kw: None)  # INVITADAS lists ana; the table does not
    assert _yo(par).status_code == 403


def test_the_resolver_receives_the_normalised_identity_and_no_fallback_by_default(ctx, par):
    vistas = []
    _modo_bd(ctx, resolver=lambda identidad, **kw: vistas.append((identidad, kw)) or UID)
    _yo(par)
    identidad, kw = vistas[0]
    assert identidad.sub == "42" and kw["respaldo"] == frozenset()


def test_the_bootstrap_fallback_passes_the_env_list_only_when_its_flag_is_set(ctx, par):
    vistas = []
    _modo_bd(ctx, resolver=lambda identidad, **kw: vistas.append(kw) or UID)
    ctx.setenv("INVITADAS_COMO_RESPALDO", "1")
    _yo(par)
    assert vistas[0]["respaldo"] == frozenset({"ana@ejemplo.es"})


def test_neon_profile_and_master_are_reported(ctx, par):
    _modo_bd(ctx, perfil=True, master=True)
    cuerpo = _yo(par).get_json()
    assert cuerpo["tiene_perfil"] is True and cuerpo["origen_master"] == "neon"


def test_a_manual_profile_without_a_master_has_no_master_origin(ctx, par):
    _modo_bd(ctx, perfil=True, master=False)
    cuerpo = _yo(par).get_json()
    assert cuerpo["tiene_perfil"] is True and cuerpo["origen_master"] is None


def test_the_legacy_drive_master_keeps_vero_working_in_database_mode(ctx, par):
    _modo_bd(ctx)
    _vero_con_master(ctx)
    cuerpo = _yo(par).get_json()
    assert cuerpo["tiene_perfil"] is True and cuerpo["origen_master"] == "drive"


def test_definitely_no_profile_is_false(ctx, par):
    _modo_bd(ctx)
    cuerpo = _yo(par).get_json()
    assert cuerpo["tiene_perfil"] is False and cuerpo["origen_master"] is None


def test_a_cold_database_while_reading_the_profile_omits_the_flag_and_logs_the_type_only(ctx, par, caplog):
    def fria(uid, conexion=None):
        raise usuarias.BaseDeDatosNoDisponible()
    _modo_bd(ctx)
    ctx.setattr(usuarias, "tiene_perfil", fria)
    with caplog.at_level(logging.WARNING):
        r = _yo(par)
    assert r.status_code == 200 and "tiene_perfil" not in r.get_json()
    assert "BaseDeDatosNoDisponible" in caplog.text and "ana@ejemplo.es" not in caplog.text


def test_an_unreachable_database_at_sign_in_is_a_generic_503(ctx, par):
    def fria(identidad, **kw):
        raise usuarias.BaseDeDatosNoDisponible()
    _modo_bd(ctx, resolver=fria)
    r = _yo(par)
    assert r.status_code == 503 and "ana@ejemplo.es" not in r.get_data(as_text=True)


def test_an_unreachable_database_still_lets_a_fallback_listed_email_in(ctx, par):
    def fria(identidad, **kw):
        raise usuarias.BaseDeDatosNoDisponible()
    _modo_bd(ctx, resolver=fria)
    ctx.setenv("INVITADAS_COMO_RESPALDO", "1")
    r = _yo(par)
    assert r.status_code == 200 and "tiene_perfil" not in r.get_json()


# --- @con_usuaria ------------------------------------------------------------------------

@pytest.fixture
def cliente_propio(ctx):
    """A throwaway app with one owner-scoped route, so the real app's routes stay untouched."""
    from flask import Flask

    app = Flask(__name__)

    @app.route("/propia")
    @srv.con_usuaria
    def propia():
        return jsonify({"usuario_id": str(g.usuario_id), "email": g.identidad.email})

    with app.test_client() as c:
        yield c


def test_con_usuaria_sets_the_current_user_id(ctx, par, cliente_propio):
    _modo_bd(ctx)
    r = cliente_propio.get("/propia", headers={"Authorization": f"Bearer {_firmar(par[1], _payload())}"})
    assert r.get_json() == {"usuario_id": str(UID), "email": "ana@ejemplo.es"}


def test_con_usuaria_rejects_without_a_token(cliente_propio):
    assert cliente_propio.get("/propia").status_code == 401
