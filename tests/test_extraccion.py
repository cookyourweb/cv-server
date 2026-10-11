"""extraccion: gates, spend ledger and kill switch, without any LLM call (spec section 4).

Gate order (REQ-4.1, S4.6): kill switch, one extraction per user, monthly cap. Consent is
checked by the route that will call the gates (C8). The tests run against a real PostgreSQL
(DATABASE_URL_PRUEBAS). The monthly sum covers EVERY row of the month, so the money tests use
an injected clock in a month no real data lives in, and clean up what they create.
"""
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import text

import base_de_datos
import extraccion
from extraccion import Rechazo, Reserva
from test_migracion_0001 import _alembic

pytestmark = pytest.mark.bd

MARZO = datetime(2031, 3, 15, 12, 0, tzinfo=timezone.utc)
EMISOR = "prueba-extraccion"
MODELO = "prueba-extraccion"
PROMPT = 3000  # characters of a typical prompt


@pytest.fixture(scope="module")
def migrado(url_de_pruebas):
    _alembic(command.upgrade, "head", url_de_pruebas)


def _limpiar():
    with base_de_datos.transaccion() as c:
        c.execute(text("DELETE FROM extracciones WHERE modelo = :m"), {"m": MODELO})
        c.execute(text("DELETE FROM usuarios WHERE emisor = :e"), {"e": EMISOR})
        c.execute(text("UPDATE ajustes SET valor = 'true'::jsonb WHERE clave = 'extraccion_activa'"))


@pytest.fixture
def bd(monkeypatch, url_de_pruebas, migrado):
    monkeypatch.delenv("EXTRACCION_ACTIVA", raising=False)
    monkeypatch.setenv("DATABASE_URL", url_de_pruebas)
    base_de_datos.cerrar()
    _limpiar()
    yield
    _limpiar()
    base_de_datos.cerrar()


def _usuaria(nombre="u1"):
    with base_de_datos.transaccion() as c:
        return c.execute(text("INSERT INTO usuarios (emisor, sub) VALUES (:e, :s) RETURNING id"),
                         {"e": EMISOR, "s": f"{nombre}-{uuid.uuid4()}"}).scalar_one()


def _gasto(importe, *, usuario_id=None, estado="completada", cuando=MARZO, coste=True):
    """A ledger row of `importe` EUR: real cost when `coste`, else only the estimate."""
    with base_de_datos.transaccion() as c:
        c.execute(text("INSERT INTO extracciones (usuario_id, modelo, estado, estimado_eur, coste_eur, creada_en) "
                       "VALUES (:u, :m, :e, :imp, :coste, :t)"),
                  {"u": usuario_id, "m": MODELO, "e": estado, "imp": importe,
                   "coste": importe if coste else None, "t": cuando})


def _filas(usuario_id=None):
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT estado, estimado_eur, coste_eur FROM extracciones WHERE modelo = :m "
                              "AND (CAST(:u AS uuid) IS NULL OR usuario_id = :u) ORDER BY creada_en"),
                         {"m": MODELO, "u": usuario_id}).all()


def _reservar(usuario_id, largo=PROMPT, ahora=MARZO):
    return extraccion.reservar(usuario_id, largo, modelo=MODELO, ahora=ahora)


ESTIMADO = extraccion.estimar_eur(PROMPT)


# --- the estimate (pure) -----------------------------------------------------------------------------

def test_the_estimate_is_ceil_chars_over_3_input_tokens_plus_max_output_for_primary_and_fallback(monkeypatch):
    monkeypatch.setattr(extraccion, "PRECIOS_PRIMARIO_EUR_POR_MTOK", (Decimal("3"), Decimal("15")))
    monkeypatch.setattr(extraccion, "PRECIOS_RESPALDO_EUR_POR_MTOK", (Decimal("1"), Decimal("2")))
    monkeypatch.setattr(extraccion, "MARGEN", Decimal("1.5"))
    monkeypatch.setattr(extraccion, "TOKENS_SALIDA_MAX", 1000)
    entrada = 334  # ceil(1000 / 3)
    primario = (entrada * Decimal(3) + 1000 * Decimal(15)) / 1_000_000
    respaldo = (entrada * Decimal(1) + 1000 * Decimal(2)) / 1_000_000
    esperado = ((primario + respaldo) * Decimal("1.5")).quantize(Decimal("0.0001"), rounding="ROUND_CEILING")
    assert extraccion.estimar_eur(1000) == esperado


def test_the_estimate_grows_with_the_prompt_and_rounds_up_to_the_ledger_precision():
    assert extraccion.estimar_eur(30_000) > extraccion.estimar_eur(3_000) > extraccion.estimar_eur(0) > 0
    assert extraccion.estimar_eur(3000).as_tuple().exponent == -4


def test_the_estimate_covers_the_worst_case_of_a_failed_primary_and_a_billed_fallback():
    solo_primario = extraccion.estimar_primario_eur(PROMPT)
    assert extraccion.estimar_eur(PROMPT) > solo_primario > 0


def test_S4_15_a_single_extraction_of_the_largest_prompt_costs_at_most_0_05(monkeypatch):
    # The prompt is capped (C8 cuts the CV text so instructions + CV fit this many characters),
    # which is what bounds the cost of one call to the amendment's 0.05 USD.
    assert extraccion.estimar_primario_eur(extraccion.MAX_CARACTERES_DE_PROMPT) <= Decimal("0.05")
    assert extraccion.estimar_eur(extraccion.MAX_CARACTERES_DE_PROMPT) <= Decimal("0.07")


def test_the_cap_and_the_prices_are_configured_constants():
    assert extraccion.TOPE_EUR == Decimal("5")
    assert extraccion.TOKENS_SALIDA_MAX == 1200
    assert extraccion.MARGEN > 1


# --- (a) kill switch: S4.2 ----------------------------------------------------------------------------------

@pytest.mark.parametrize("valor", ["false", "FALSE", "0", "no", "off"])
def test_S4_2_the_environment_hard_off_refuses_without_touching_the_database(monkeypatch, valor):
    def prohibido(*args, **kwargs):
        raise AssertionError("the hard-off must not reach the database")
    monkeypatch.setattr(base_de_datos, "motor", prohibido)
    monkeypatch.setenv("EXTRACCION_ACTIVA", valor)
    assert _reservar("cualquiera") == Rechazo("desactivada")


def test_S4_2_the_switch_row_off_refuses_and_reserves_nothing(bd):
    extraccion_u = _usuaria()
    with base_de_datos.transaccion() as c:
        extraccion.fijar_interruptor(c, False)
    assert _reservar(extraccion_u) == Rechazo("desactivada")
    assert _filas() == []


def test_the_switch_row_is_read_on_every_request_so_it_works_without_a_redeploy(bd):
    a, b = _usuaria("a"), _usuaria("b")
    with base_de_datos.transaccion() as c:
        extraccion.fijar_interruptor(c, False)
    assert _reservar(a) == Rechazo("desactivada")
    with base_de_datos.transaccion() as c:
        extraccion.fijar_interruptor(c, True)
    assert isinstance(_reservar(b), Reserva)


def test_a_missing_switch_row_fails_closed(bd):
    with base_de_datos.transaccion() as c:
        c.execute(text("DELETE FROM ajustes WHERE clave = 'extraccion_activa'"))
    try:
        assert _reservar(_usuaria()) == Rechazo("desactivada")
    finally:
        with base_de_datos.transaccion() as c:
            c.execute(text("INSERT INTO ajustes (clave, valor) VALUES ('extraccion_activa', 'true'::jsonb) "
                           "ON CONFLICT (clave) DO UPDATE SET valor = 'true'::jsonb"))


@pytest.mark.parametrize("valor", ["true", "1", "yes", ""])
def test_any_other_environment_value_leaves_the_decision_to_the_switch_row(bd, monkeypatch, valor):
    monkeypatch.setenv("EXTRACCION_ACTIVA", valor)
    assert isinstance(_reservar(_usuaria()), Reserva)


# --- (b) one extraction per user: S4.3 ---------------------------------------------------------------------------

def test_a_reservation_inserts_a_reservada_row_with_the_estimate(bd):
    usuaria = _usuaria()
    reserva = _reservar(usuaria)
    assert isinstance(reserva, Reserva) and reserva.estimado_eur == ESTIMADO
    (fila,) = _filas(usuaria)
    assert (fila.estado, fila.estimado_eur, fila.coste_eur) == ("reservada", ESTIMADO, None)


def test_S4_3_a_second_request_is_refused_and_adds_no_row(bd):
    usuaria = _usuaria()
    assert isinstance(_reservar(usuaria), Reserva)
    assert _reservar(usuaria) == Rechazo("ya_usada")
    assert len(_filas(usuaria)) == 1


def test_a_completed_extraction_also_uses_the_attempt(bd):
    usuaria = _usuaria()
    reserva = _reservar(usuaria)
    assert extraccion.marcar_completada(reserva.id, Decimal("0.0213"), 1800, 640) is True
    assert _reservar(usuaria) == Rechazo("ya_usada")


def test_another_user_is_not_affected_by_someone_elses_attempt(bd):
    assert isinstance(_reservar(_usuaria("a")), Reserva)
    assert isinstance(_reservar(_usuaria("b")), Reserva)


# --- completion and failure ----------------------------------------------------------------------------------------

def test_completing_records_the_real_cost_and_tokens(bd):
    usuaria = _usuaria()
    reserva = _reservar(usuaria)
    assert extraccion.marcar_completada(reserva.id, Decimal("0.0213"), 1800, 640) is True
    with base_de_datos.transaccion() as c:
        fila = c.execute(text("SELECT estado, coste_eur, tokens_entrada, tokens_salida FROM extracciones "
                              "WHERE id = :i"), {"i": reserva.id}).one()
    assert (fila.estado, fila.coste_eur, fila.tokens_entrada, fila.tokens_salida) == ("completada", Decimal("0.0213"), 1800, 640)


def test_a_finished_reservation_cannot_be_finished_again(bd):
    reserva = _reservar(_usuaria())
    assert extraccion.marcar_completada(reserva.id, Decimal("0.01"), 1, 1) is True
    assert extraccion.marcar_completada(reserva.id, Decimal("0.02"), 1, 1) is False
    assert extraccion.marcar_fallida(reserva.id) is False


def test_amendment_a_failed_chain_keeps_the_users_attempt_and_its_estimate_counts_toward_the_cap(bd):
    usuaria = _usuaria()
    reserva = _reservar(usuaria)
    assert extraccion.marcar_fallida(reserva.id) is True
    (fila,) = _filas(usuaria)
    assert fila.estado == "fallida" and fila.coste_eur is None and fila.estimado_eur == ESTIMADO
    # the attempt is NOT consumed: she can try again later
    nueva = _reservar(usuaria)
    assert isinstance(nueva, Reserva) and nueva.id != reserva.id
    # ...and the failed call still weighs on the month: both estimates are in the sum
    with base_de_datos.transaccion() as c:
        assert extraccion.gasto_del_mes(c, MARZO) == 2 * ESTIMADO


def test_a_failed_attempt_can_be_retried_only_while_no_other_attempt_is_open_or_done(bd):
    usuaria = _usuaria()
    primera = _reservar(usuaria)
    extraccion.marcar_fallida(primera.id)
    segunda = _reservar(usuaria)
    assert _reservar(usuaria) == Rechazo("ya_usada")  # the retry is open now
    extraccion.marcar_completada(segunda.id, Decimal("0.02"), 1, 1)
    assert _reservar(usuaria) == Rechazo("ya_usada")


# --- (c) monthly cap: S4.4, S2.7 --------------------------------------------------------------------------------------

def test_S4_4_when_the_month_plus_the_estimate_exceeds_5_eur_it_is_refused(bd):
    usuaria = _usuaria()
    _gasto(Decimal("5") - ESTIMADO + Decimal("0.0001"))  # e.g. 4.99xx: one cent of a cent too much
    assert _reservar(usuaria) == Rechazo("tope")
    assert _filas(usuaria) == []


def test_S4_4_exactly_5_eur_is_allowed(bd):
    usuaria = _usuaria()
    _gasto(Decimal("5") - ESTIMADO)
    reserva = _reservar(usuaria)
    assert isinstance(reserva, Reserva)
    with base_de_datos.transaccion() as c:
        assert extraccion.gasto_del_mes(c, MARZO) == Decimal("5")
    assert _reservar(_usuaria("otra")) == Rechazo("tope")  # now there is no room at all


def test_the_sum_uses_the_real_cost_when_there_is_one_and_the_estimate_otherwise(bd):
    _gasto(Decimal("1.0000"), coste=True)                                 # real 1.0000
    _gasto(Decimal("2.0000"), estado="reservada", coste=False)            # in flight: estimate counts
    _gasto(Decimal("0.5000"), estado="fallida", coste=False)              # failed: estimate counts
    with base_de_datos.transaccion() as c:
        assert extraccion.gasto_del_mes(c, MARZO) == Decimal("3.5000")


def test_S2_7_rows_of_deleted_users_still_count(bd):
    _gasto(Decimal("5") - ESTIMADO + Decimal("0.0001"), usuario_id=None)  # orphaned by an account deletion
    assert _reservar(_usuaria()) == Rechazo("tope")


def test_only_the_current_utc_month_counts(bd):
    _gasto(Decimal("4.9"), cuando=datetime(2031, 2, 28, 23, 59, 59, tzinfo=timezone.utc))
    _gasto(Decimal("4.9"), cuando=datetime(2031, 4, 1, 0, 0, 0, tzinfo=timezone.utc))
    assert isinstance(_reservar(_usuaria()), Reserva)
    _gasto(Decimal("4.97"), cuando=datetime(2031, 3, 1, 0, 0, 0, tzinfo=timezone.utc))  # first instant of March
    assert _reservar(_usuaria("b")) == Rechazo("tope")


def test_a_naive_clock_is_rejected_so_the_month_boundary_is_always_utc(bd):
    with pytest.raises(ValueError):
        _reservar(_usuaria(), ahora=datetime(2031, 3, 15, 12, 0))


# --- S4.6: order -----------------------------------------------------------------------------------------------------------

def test_S4_6_the_switch_is_reported_before_everything_else(bd):
    usuaria = _usuaria()
    _reservar(usuaria)                        # already used
    _gasto(Decimal("5"))                      # cap exhausted
    with base_de_datos.transaccion() as c:
        extraccion.fijar_interruptor(c, False)
    assert _reservar(usuaria) == Rechazo("desactivada")


def test_S4_6_an_used_attempt_is_reported_before_the_cap(bd):
    usuaria = _usuaria()
    _reservar(usuaria)
    _gasto(Decimal("5"))
    assert _reservar(usuaria) == Rechazo("ya_usada")


def test_S4_6_the_cap_is_reported_last(bd):
    _gasto(Decimal("5"))
    assert _reservar(_usuaria()) == Rechazo("tope")


# --- S4.5: concurrency -------------------------------------------------------------------------------------------------------

def test_S4_5_ten_concurrent_requests_with_room_for_one_make_at_most_one_reservation(bd, url_de_pruebas):
    usuarias = [_usuaria(f"c{n}") for n in range(10)]
    _gasto(Decimal("5") - ESTIMADO)           # room for exactly one more estimate
    resultados, errores = [], []
    barrera = threading.Barrier(len(usuarias))

    def pedir(usuaria):
        motor = base_de_datos.crear_motor(url_de_pruebas)  # its own connection: real concurrency
        try:
            barrera.wait(timeout=20)
            with motor.begin() as conexion:
                resultados.append(extraccion.reservar_en(conexion, usuaria, PROMPT, modelo=MODELO, ahora=MARZO))
        except Exception as error:  # a thread must report, not die silently
            errores.append(type(error).__name__)
        finally:
            motor.dispose()

    hilos = [threading.Thread(target=pedir, args=(u,)) for u in usuarias]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)
    assert errores == [] and len(resultados) == 10
    assert sum(isinstance(r, Reserva) for r in resultados) == 1
    assert sum(r == Rechazo("tope") for r in resultados) == 9
    with base_de_datos.transaccion() as c:
        assert extraccion.gasto_del_mes(c, MARZO) <= Decimal("5")


def test_the_same_user_double_clicking_concurrently_gets_one_reservation(bd, url_de_pruebas):
    usuaria = _usuaria()
    resultados = []
    barrera = threading.Barrier(5)

    def pedir():
        motor = base_de_datos.crear_motor(url_de_pruebas)
        try:
            barrera.wait(timeout=20)
            with motor.begin() as conexion:
                resultados.append(extraccion.reservar_en(conexion, usuaria, PROMPT, modelo=MODELO, ahora=MARZO))
        finally:
            motor.dispose()

    hilos = [threading.Thread(target=pedir) for _ in range(5)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)
    assert sum(isinstance(r, Reserva) for r in resultados) == 1
    assert len(_filas(usuaria)) == 1


# --- the switch endpoint: see tests/test_ajustes.py ---------------------------------------------------------------------
