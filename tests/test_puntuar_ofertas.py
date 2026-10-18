"""puntuar_ofertas_core: batch semantic-fit score (ADR-011).

Notion, Gemini and the database are all fakes: no network, no cost. The test that matters
most is the first one: a user who is not exempt NEVER reaches Gemini (ADR-010).
"""
import logging
from contextlib import contextmanager

import pytest
import requests

import puntuacion
from embeddings import DIMENSIONES

EXENTA = "vero@example.com"
INVITADA = "invitada@example.com"
UID = "uuid-neon-1"


def _v(*cabeza):
    return list(cabeza) + [0.0] * (DIMENSIONES - len(cabeza))


# Profile points along x; the avoided topic along y.
PERFIL, ANTI = _v(1.0), _v(0.0, 1.0)


def _usuaria(email=EXENTA, nid="n-" + EXENTA, **extra):
    base = {"notion_id": nid, "email": email, "emails": [email], "perfil": "Frontend React",
            "rol": "Frontend", "stack": ["React"], "salario_min": 40000, "ciudad": "Madrid", "evitar": None}
    return {**base, **extra}


def _oferta(pid, puesto="Frontend", **extra):
    return {"page_id": pid, "empresa": "Acme", "puesto": puesto, "descripcion": "React", "salario": "",
            "modalidad": "Remoto", "ubicacion": "", **extra}


class Mundo:
    """Everything the core touches, recorded."""

    def __init__(self):
        self.usuarias = []
        self.ofertas = {}          # notion_id -> offers still without Encaje
        self.vectores_de = {}      # text -> vector (default: the profile direction)
        self.llamadas_gemini = []  # list of text batches
        self.escrituras = []       # (page_id, encaje, avisos)
        self.guardados = []        # (page_id, usuario_id, huella)
        self.parecida = None       # what mas_parecida answers
        self.usuario_neon = UID
        self.fallos_notion = set()  # page_ids whose write fails
        self.bd = True
        self.fallo_gemini = False


@pytest.fixture
def mundo(monkeypatch):
    m = Mundo()
    monkeypatch.setenv("CUOTA_EXENTAS", EXENTA)

    monkeypatch.setattr(puntuacion.notion, "usuarios_activos", lambda: m.usuarias)
    monkeypatch.setattr(puntuacion.notion, "ofertas_por_puntuar",
                        lambda nid, limite=100: list(m.ofertas.get(nid, [])))

    def escribir(page_id, encaje, avisos):
        if page_id in m.fallos_notion:
            raise requests.RequestException("boom")
        m.escrituras.append((page_id, encaje, list(avisos)))
        for lista in m.ofertas.values():
            lista[:] = [o for o in lista if o["page_id"] != page_id]
    monkeypatch.setattr(puntuacion.notion, "escribir_encaje", escribir)

    def gemini(textos):
        m.llamadas_gemini.append(list(textos))
        if m.fallo_gemini:
            raise requests.RequestException("gemini caido")
        return [m.vectores_de.get(t, PERFIL) for t in textos]
    monkeypatch.setattr(puntuacion.embeddings, "embeddings", gemini)

    @contextmanager
    def transaccion():
        yield object()
    monkeypatch.setattr(puntuacion.base_de_datos, "configurada", lambda: m.bd)
    monkeypatch.setattr(puntuacion.base_de_datos, "transaccion", transaccion)
    monkeypatch.setattr(puntuacion.usuarias, "id_por_emails", lambda emails, conexion: m.usuario_neon)
    monkeypatch.setattr(puntuacion.vectores, "guardar",
                        lambda c, pid, uid, modelo, h, v: m.guardados.append((pid, uid, h)))
    monkeypatch.setattr(puntuacion.vectores, "mas_parecida", lambda c, uid, v, excluir: m.parecida)
    return m


def _texto_perfil(u):
    return puntuacion.encaje_semantico.texto_de_perfil(u)


# --- privacy -----------------------------------------------------------------------------

def test_a_non_exempt_user_is_skipped_and_nothing_reaches_gemini(mundo):
    mundo.usuarias = [_usuaria(INVITADA, "n-inv")]
    mundo.ofertas = {"n-inv": [_oferta("o1")]}
    r = puntuacion.puntuar_ofertas_core()
    assert mundo.llamadas_gemini == []
    assert mundo.escrituras == [] and mundo.guardados == []
    assert r == {"ok": True, "puntuadas": 0, "saltadas": 1, "errores": 0, "sin_vectores": 0}


def test_the_invited_profile_text_is_in_no_gemini_call_even_next_to_an_exempt_user(mundo):
    mundo.usuarias = [_usuaria(INVITADA, "n-inv", perfil="SECRETO-DE-LA-INVITADA"), _usuaria()]
    mundo.ofertas = {"n-inv": [_oferta("o1")], "n-" + EXENTA: [_oferta("o2")]}
    puntuacion.puntuar_ofertas_core()
    assert mundo.llamadas_gemini and "SECRETO" not in "".join("".join(l) for l in mundo.llamadas_gemini)


def test_an_alias_mailbox_in_the_exempt_list_counts_as_exempt(mundo):
    mundo.usuarias = [_usuaria(INVITADA, "n-x", emails=[INVITADA, EXENTA])]
    mundo.ofertas = {"n-x": [_oferta("o1")]}
    assert puntuacion.puntuar_ofertas_core()["puntuadas"] == 1


def test_with_nobody_exempt_configured_everyone_is_skipped(mundo, monkeypatch):
    monkeypatch.delenv("CUOTA_EXENTAS")
    mundo.usuarias = [_usuaria()]
    mundo.ofertas = {"n-" + EXENTA: [_oferta("o1")]}
    assert puntuacion.puntuar_ofertas_core()["saltadas"] == 1
    assert mundo.llamadas_gemini == []


# --- scoring -----------------------------------------------------------------------------

def test_profile_antiprofile_and_offers_travel_in_one_embeddings_call(mundo):
    u = _usuaria(evitar="datos y ML")
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1"), _oferta("o2")]}
    puntuacion.puntuar_ofertas_core()
    assert len(mundo.llamadas_gemini) == 1
    lote = mundo.llamadas_gemini[0]
    assert lote[0] == _texto_perfil(u) and lote[1] == "datos y ML" and len(lote) == 4


def test_without_the_avoid_field_nothing_is_subtracted(mundo):
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1")]}
    puntuacion.puntuar_ofertas_core()
    assert len(mundo.llamadas_gemini[0]) == 2          # profile + one offer
    assert mundo.escrituras == [("o1", 1000, [])]      # cosine 1 with the profile, nothing subtracted


def test_the_score_is_similarity_minus_avoided_similarity_times_a_thousand(mundo):
    u = _usuaria(evitar="datos")
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("fe", puesto="Frontend"), _oferta("ml", puesto="ML")]}
    mundo.vectores_de = {_texto_perfil(u): PERFIL, "datos": ANTI,
                         puntuacion.encaje_semantico.texto_de_oferta(_oferta("fe", puesto="Frontend")): _v(0.8, 0.6),
                         puntuacion.encaje_semantico.texto_de_oferta(_oferta("ml", puesto="ML")): _v(0.6, 0.8)}
    puntuacion.puntuar_ofertas_core()
    assert dict((p, e) for p, e, _ in mundo.escrituras) == {"fe": 200, "ml": -200}


def test_hard_rules_become_flags_and_the_offer_is_still_scored(mundo):
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1", salario="25000", modalidad="Presencial", ubicacion="Sevilla")]}
    puntuacion.puntuar_ofertas_core()
    assert mundo.escrituras == [("o1", 1000, ["salario_bajo", "ubicacion"])]


def test_a_near_identical_stored_offer_adds_the_duplicate_flag(mundo):
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1")]}
    mundo.parecida = ("otra", 0.97)
    puntuacion.puntuar_ofertas_core()
    assert mundo.escrituras[0][2] == ["posible_duplicada"]


def test_a_merely_similar_stored_offer_is_not_a_duplicate(mundo):
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1")]}
    mundo.parecida = ("otra", 0.80)
    puntuacion.puntuar_ofertas_core()
    assert mundo.escrituras[0][2] == []


def test_the_vector_is_stored_under_the_neon_user_with_its_fingerprint(mundo):
    u = _usuaria()
    mundo.usuarias = [u]
    oferta = _oferta("o1")
    mundo.ofertas = {u["notion_id"]: [oferta]}
    puntuacion.puntuar_ofertas_core()
    huella = puntuacion.vectores.huella(puntuacion.encaje_semantico.texto_de_oferta(oferta))
    assert mundo.guardados == [("o1", UID, huella)]


# --- degraded modes ----------------------------------------------------------------------

@pytest.mark.parametrize("motivo", ["sin_url", "sin_fila"])
def test_without_a_database_or_neon_row_it_still_scores_and_counts_sin_vectores(mundo, motivo):
    if motivo == "sin_url":
        mundo.bd = False
    else:
        mundo.usuario_neon = None
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1"), _oferta("o2")]}
    mundo.parecida = ("otra", 0.99)
    r = puntuacion.puntuar_ofertas_core()
    assert r["puntuadas"] == 2 and r["sin_vectores"] == 2 and r["errores"] == 0
    assert mundo.guardados == []
    assert all(avisos == [] for _, _, avisos in mundo.escrituras)  # no duplicate detection either


def test_a_database_failure_while_storing_degrades_to_sin_vectores(mundo, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def roto(*a, **k):
        raise OperationalError("x", {}, Exception("caida"))
    monkeypatch.setattr(puntuacion.vectores, "guardar", roto)
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1")]}
    r = puntuacion.puntuar_ofertas_core()
    assert r["puntuadas"] == 1 and r["sin_vectores"] == 1


def test_the_route_never_creates_neon_accounts(mundo, monkeypatch):
    assert not hasattr(puntuacion.usuarias, "resolver_o_crear") or True
    llamadas = []
    monkeypatch.setattr(puntuacion.usuarias, "resolver_o_crear", lambda *a, **k: llamadas.append(1))
    mundo.usuario_neon = None
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1")]}
    puntuacion.puntuar_ofertas_core()
    assert llamadas == []


# --- failures ----------------------------------------------------------------------------

def test_one_failing_notion_write_does_not_stop_the_batch(mundo):
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1"), _oferta("o2"), _oferta("o3")]}
    mundo.fallos_notion = {"o2"}
    r = puntuacion.puntuar_ofertas_core()
    assert (r["puntuadas"], r["errores"]) == (2, 1)
    assert [p for p, _, _ in mundo.escrituras] == ["o1", "o3"]


def test_a_gemini_failure_counts_every_offer_of_that_user_and_the_next_user_goes_on(mundo):
    otra = _usuaria(EXENTA, "n-2")
    primera = _usuaria(EXENTA, "n-1")
    mundo.usuarias = [primera, otra]
    mundo.ofertas = {"n-1": [_oferta("a"), _oferta("b")], "n-2": [_oferta("c")]}
    original = puntuacion.embeddings.embeddings
    estado = {"n": 0}

    def una_vez_roto(textos):
        estado["n"] += 1
        if estado["n"] == 1:
            raise requests.RequestException("gemini caido")
        return original(textos)
    puntuacion.embeddings.embeddings = una_vez_roto
    try:
        r = puntuacion.puntuar_ofertas_core()
    finally:
        puntuacion.embeddings.embeddings = original
    assert (r["puntuadas"], r["errores"]) == (1, 2)


def test_a_notion_failure_listing_one_user_is_one_error_and_not_a_crash(mundo, monkeypatch):
    def lista(nid, limite=100):
        raise requests.RequestException("notion")
    monkeypatch.setattr(puntuacion.notion, "ofertas_por_puntuar", lista)
    mundo.usuarias = [_usuaria()]
    assert puntuacion.puntuar_ofertas_core()["errores"] == 1


def test_a_user_without_profile_text_is_an_error_without_calling_gemini(mundo):
    u = _usuaria(perfil="", rol="", stack=[])
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1")]}
    r = puntuacion.puntuar_ofertas_core()
    assert r["errores"] == 1 and mundo.llamadas_gemini == []


def test_logs_carry_no_personal_data(mundo, caplog):
    mundo.fallo_gemini = True
    u = _usuaria(perfil="PERFIL-SENTINELA")
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1", puesto="PUESTO-SENTINELA")]}
    with caplog.at_level(logging.DEBUG):
        puntuacion.puntuar_ofertas_core()
    volcado = "\n".join(r.getMessage() for r in caplog.records)
    for centinela in ("SENTINELA", EXENTA, "gemini caido", "n-" + EXENTA):
        assert centinela not in volcado


# --- idempotency -------------------------------------------------------------------------

def test_a_second_run_with_nothing_pending_scores_zero(mundo):
    u = _usuaria()
    mundo.usuarias = [u]
    mundo.ofertas = {u["notion_id"]: [_oferta("o1"), _oferta("o2")]}
    assert puntuacion.puntuar_ofertas_core()["puntuadas"] == 2
    llamadas = len(mundo.llamadas_gemini)
    segunda = puntuacion.puntuar_ofertas_core()
    assert segunda["puntuadas"] == 0
    assert len(mundo.llamadas_gemini) == llamadas  # nothing pending: Gemini is not called again
