"""Quota and cap on /generar-cv and /generar-carta, through the Flask client (no real model).

The LLM is always a fake: every refusal test asserts it was NEVER called. The database is a real
PostgreSQL; ledger rows are told apart by a test-only model id and removed afterwards. Users are the
invited test personas of test_rutas_alta, mapped to their mailbox exactly like n8n's calls are.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from test_rutas_alta import _llamar, bd, cliente, migrado, par, personas  # noqa: F401

import base_de_datos
import cuota
import server as srv
from drive import MasterCV
from llm import RespuestaLLM

pytestmark = pytest.mark.bd

CLAVE = "clave-de-prueba-larga-y-aleatoria"
MODELO = "prueba-ruta-cuota"
DESCRIPCION = "Angular y TypeScript. " * 30


class LLMFalso:
    def __init__(self, error=None, tokens=(1800, 700)):
        self.llamadas, self.error, self.tokens = [], error, tokens

    def __call__(self, prompt, **kw):
        self.llamadas.append(kw)
        if self.error:
            raise self.error
        return RespuestaLLM("HEADLINE: Frontend\nExperiencia\nTrabajo real." if kw.get("max_tokens") == 4096
                            else "Estimados/as, soy frontend con Angular.", MODELO, *self.tokens)


def _limpiar():
    with base_de_datos.transaccion() as c:
        c.execute(text("DELETE FROM gastos_generacion WHERE modelo = :m"), {"m": MODELO})


@pytest.fixture(autouse=True)
def entorno(monkeypatch, bd):  # noqa: F811
    monkeypatch.setattr(srv, "CLAVE_MAQUINA", CLAVE)
    monkeypatch.setattr(srv, "CV_MODEL", MODELO)
    monkeypatch.setattr(srv, "CARTA_MODEL", MODELO)
    monkeypatch.setattr(srv, "buscar_oferta_en_notion", lambda e, p: None)
    monkeypatch.setattr(srv, "buscar_usuario_por_email", lambda e: {"nombre": "Ana", "cv_master_url": ""})
    monkeypatch.setattr(srv, "leer_cv_master_desde_drive", lambda u, i: MasterCV("", ""))
    monkeypatch.setattr(srv, "generar_docx_con_cabecera", lambda *a, **k: b"docx")
    monkeypatch.setattr(srv, "subir_cv_a_drive", lambda *a, **k: "https://drive/cv")
    monkeypatch.setattr(srv, "guardar_link_cv_en_notion", lambda *a, **k: True)
    monkeypatch.setattr(cuota, "TOPE_EUR", Decimal("100000"))
    monkeypatch.setattr(cuota, "aviso_configurado", lambda: False)
    monkeypatch.delenv("CUOTA_EXENTAS", raising=False)
    _limpiar()
    yield
    _limpiar()


@pytest.fixture
def llm_falso(monkeypatch):
    """The fake answers on BOTH chains (the owner's and the invited one): the tests below that
    care about which chain ran use `cadenas` instead."""
    falso = LLMFalso()
    monkeypatch.setattr(srv, "call_llm_calidad", falso)
    monkeypatch.setattr(srv, "call_llm_invitada", falso)
    return falso


@pytest.fixture
def cadenas(monkeypatch):
    """One fake per chain, to tell which one a request used."""
    duena, invitada = LLMFalso(), LLMFalso()
    monkeypatch.setattr(srv, "call_llm_calidad", duena)
    monkeypatch.setattr(srv, "call_llm_invitada", invitada)
    return duena, invitada


@pytest.fixture
def ana(cliente, personas):  # noqa: F811
    """Ana exists in Neon (her first request creates the user)."""
    _llamar(cliente, "GET", "/yo", personas["ana"])
    return personas["ana"]


def _post(ruta, persona, **cambios):
    datos = {"email": persona.email, "empresa": "ACME", "puesto": "Frontend", "descripcion": DESCRIPCION,
             "idioma": "es", **cambios}
    r = srv.app.test_client().post(ruta, json=datos, headers={"X-Clave-Maquina": CLAVE})
    return r.status_code, r.get_json()


def _libro(persona):
    with base_de_datos.transaccion() as c:
        return c.execute(text(
            "SELECT g.tipo, g.unidades, g.estado, g.coste_estimado, g.coste_real FROM gastos_generacion g "
            "JOIN usuario_emails e ON e.usuario_id = g.usuario_id WHERE e.email = :e AND g.modelo = :m "
            "ORDER BY g.creado_en"), {"e": persona.email, "m": MODELO}).all()


def _libro_id(persona):
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT usuario_id FROM usuario_emails WHERE email = :e"),
                         {"e": persona.email}).scalar_one()


def _sembrar(persona, unidades="8", coste="0.01"):
    with base_de_datos.transaccion() as c:
        c.execute(text(
            "INSERT INTO gastos_generacion (usuario_id, tipo, modelo, unidades, estado, coste_estimado, coste_real) "
            "SELECT usuario_id, 'cv', :m, :n, 'completada', :c, :c FROM usuario_emails WHERE email = :e"),
            {"m": MODELO, "n": unidades, "c": coste, "e": persona.email})


def _yo(cliente, persona):
    return _llamar(cliente, "GET", "/yo", persona).get_json()


def _primero_del_mes_siguiente():
    return cuota.renovacion(datetime.now(timezone.utc)).isoformat()


# --- refusals happen before any model ----------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/generar-carta", "/generar-cv"])
def test_over_quota_answers_429_with_the_reset_date_and_never_calls_the_model(ana, llm_falso, ruta):
    _sembrar(ana, "8")
    estado, cuerpo = _post(ruta, ana)
    assert estado == 429 and llm_falso.llamadas == []
    assert cuerpo == {"ok": False, "error": cuerpo["error"], "motivo": "cuota",
                      "se_renueva": _primero_del_mes_siguiente()}
    assert ana.email not in str(cuerpo)


@pytest.mark.parametrize("ruta", ["/generar-carta", "/generar-cv"])
def test_over_the_global_cap_answers_429_tope_and_never_calls_the_model(ana, llm_falso, monkeypatch, ruta):
    monkeypatch.setattr(cuota, "TOPE_EUR", Decimal("0.0001"))
    estado, cuerpo = _post(ruta, ana)
    assert estado == 429 and llm_falso.llamadas == []
    assert cuerpo["motivo"] == "tope" and cuerpo["se_renueva"] == _primero_del_mes_siguiente()
    assert _libro(ana) == []


def test_a_database_failure_while_reserving_answers_503_without_calling_the_model(ana, llm_falso, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def cae(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("host secreto-db.internal refused"))
    monkeypatch.setattr(cuota, "reservar", cae)
    estado, cuerpo = _post("/generar-carta", ana)
    assert estado == 503 and cuerpo["motivo"] == "indisponible" and llm_falso.llamadas == []
    assert "secreto-db" not in str(cuerpo)


# --- the happy path and the refunds -------------------------------------------------------------------

def test_a_letter_costs_0_3_and_a_cv_0_7_so_a_pair_is_one_application(cliente, ana, llm_falso):
    assert _post("/generar-carta", ana)[0] == 200
    assert _post("/generar-cv", ana)[0] == 200
    assert [(f.tipo, f.unidades, f.estado) for f in _libro(ana)] == [
        ("carta", Decimal("0.30"), "completada"), ("cv", Decimal("0.70"), "completada")]
    with base_de_datos.transaccion() as c:
        assert cuota.unidades_usadas(c, _libro_id(ana)) == Decimal("1.0")
    assert all(f.coste_real is not None and f.coste_real < f.coste_estimado for f in _libro(ana))


def test_the_model_is_called_with_the_same_arguments_as_before(ana, llm_falso):
    _post("/generar-carta", ana)
    _post("/generar-cv", ana)
    assert [(k["model"], k["max_tokens"]) for k in llm_falso.llamadas] == [(MODELO, 1500), (MODELO, 4096)]


@pytest.mark.parametrize("ruta, esperado", [("/generar-carta", 503), ("/generar-cv", 503)])
def test_a_provider_failure_keeps_answering_503_gives_the_units_back_and_keeps_the_cost(
        cliente, ana, monkeypatch, ruta, esperado):
    falso = LLMFalso(error=RuntimeError("Todos los LLMs fallaron"))
    monkeypatch.setattr(srv, "call_llm_calidad", falso)
    monkeypatch.setattr(srv, "call_llm_invitada", falso)
    estado, cuerpo = _post(ruta, ana)
    assert estado == esperado and cuerpo["ok"] is False and "Todos los LLMs" in cuerpo["error"]
    (fila,) = _libro(ana)
    assert fila.estado == "fallida" and fila.coste_real is None and fila.coste_estimado > 0
    with base_de_datos.transaccion() as c:
        assert cuota.unidades_usadas(c, _libro_id(ana)) == 0
        assert cuota.gasto_del_mes(c) >= fila.coste_estimado


def test_the_last_unit_is_usable_and_the_next_request_is_refused(ana, llm_falso):
    _sembrar(ana, "7.7")
    assert _post("/generar-carta", ana)[0] == 200   # 7.7 + 0.3 = 8.0
    assert _post("/generar-carta", ana)[0] == 429
    assert len(llm_falso.llamadas) == 1


# --- who is never touched ------------------------------------------------------------------------------

def test_the_owner_listed_in_cuota_exentas_is_never_counted_or_blocked_and_sees_no_quota(cliente, ana, llm_falso,
                                                                                         monkeypatch):
    _sembrar(ana, "8")
    monkeypatch.setenv("CUOTA_EXENTAS", f"otra@example.com, {ana.email.upper()}")
    assert _post("/generar-carta", ana)[0] == 200 and _post("/generar-cv", ana)[0] == 200
    assert len(_libro(ana)) == 1                       # only the seeded row


def test_the_legacy_owner_without_a_neon_row_is_never_counted_or_blocked(personas, llm_falso):
    class Vero:
        email = "vero-legado@example.com"
    with base_de_datos.transaccion() as c:
        antes = c.execute(text("SELECT count(*) FROM gastos_generacion")).scalar_one()
    assert _post("/generar-carta", Vero)[0] == 200 and _post("/generar-cv", Vero)[0] == 200
    with base_de_datos.transaccion() as c:
        assert c.execute(text("SELECT count(*) FROM gastos_generacion")).scalar_one() == antes
    assert len(llm_falso.llamadas) == 2


def test_without_database_url_the_routes_never_touch_the_database(personas, llm_falso, monkeypatch):
    monkeypatch.delenv("DATABASE_URL")

    def prohibido(*args, **kwargs):
        raise AssertionError("legacy mode must not touch the database")
    with monkeypatch.context() as local:  # undone before the fixture teardown needs the database
        local.setattr(base_de_datos, "transaccion", prohibido)
        local.setattr(base_de_datos, "motor", prohibido)
        assert _post("/generar-carta", personas["ana"])[0] == 200
        assert _post("/generar-cv", personas["ana"])[0] == 200
    assert len(llm_falso.llamadas) == 2


# --- which provider chain wrote it --------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/generar-carta", "/generar-cv"])
def test_an_invited_user_is_generated_with_claude_and_groq_only_never_the_general_cascade(ana, cadenas, ruta):
    duena, invitada = cadenas
    assert _post(ruta, ana)[0] == 200
    assert duena.llamadas == [] and len(invitada.llamadas) == 1


@pytest.mark.parametrize("ruta", ["/generar-carta", "/generar-cv"])
def test_an_invited_user_never_reaches_gemini_even_when_claude_and_groq_fail(ana, monkeypatch, ruta):
    import llm

    def solo_groq(url, **kwargs):
        assert "generativelanguage" not in url, "an invited user's CV reached Gemini"
        raise RuntimeError("down")

    def cae(*a, **k):
        raise RuntimeError("down")

    def prohibida(*a, **k):
        pytest.fail("the general cascade must not run for an invited user")
    monkeypatch.setattr(llm, "GEMINI_API_KEY", "gemini-de-prueba")
    monkeypatch.setattr(llm, "call_claude", cae)
    monkeypatch.setattr(llm.requests, "post", solo_groq)
    monkeypatch.setattr(llm.CascadaCasera, "completar", prohibida)
    monkeypatch.setattr(srv, "call_llm_calidad", prohibida)
    estado, cuerpo = _post(ruta, ana)
    assert estado == 503 and cuerpo["ok"] is False


@pytest.mark.parametrize("ruta", ["/generar-carta", "/generar-cv"])
def test_legacy_and_exempt_users_keep_the_owner_chain(personas, cadenas, ana, monkeypatch, ruta):
    duena, invitada = cadenas

    class Vero:
        email = "vero-legado@example.com"
    assert _post(ruta, Vero)[0] == 200                       # no Neon user
    monkeypatch.setenv("CUOTA_EXENTAS", ana.email)
    assert _post(ruta, ana)[0] == 200                        # exempt
    monkeypatch.delenv("CUOTA_EXENTAS")
    monkeypatch.setattr(cuota.base_de_datos, "configurada", lambda: False)
    assert _post(ruta, ana)[0] == 200                        # no database at all
    assert len(duena.llamadas) == 3 and invitada.llamadas == []
