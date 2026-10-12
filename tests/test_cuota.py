"""cuota against a real PostgreSQL: per-user units, global cap, refunds, alarm (no model is called).

The monthly sums cover EVERY ledger row, so these tests use an injected clock in months no real
data lives in (2032) and delete the rows they create (told apart by a test-only model id).
"""
import logging
import threading
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import text

import base_de_datos
import cuota
from cuota import Rechazo, Reserva
from llm import RespuestaLLM
from test_migracion_0001 import _alembic

pytestmark = pytest.mark.bd

MAYO = datetime(2032, 5, 15, 12, 0, tzinfo=timezone.utc)
JUNIO = datetime(2032, 6, 15, 12, 0, tzinfo=timezone.utc)
EMISOR = "prueba-cuota"
MODELO = "prueba-cuota"
PROMPT = 3000
ESTIMADO = cuota.estimar_eur(PROMPT, max_tokens=4096)


@pytest.fixture(scope="module")
def migrado(url_de_pruebas):
    _alembic(command.upgrade, "head", url_de_pruebas)


def _limpiar():
    with base_de_datos.transaccion() as c:
        c.execute(text("DELETE FROM gastos_generacion WHERE modelo = :m"), {"m": MODELO})
        c.execute(text("DELETE FROM usuarios WHERE emisor = :e"), {"e": EMISOR})
        c.execute(text("DELETE FROM avisos_gasto WHERE mes >= '2032-01-01' AND mes < '2033-01-01'"))


@pytest.fixture
def bd(monkeypatch, url_de_pruebas, migrado):
    monkeypatch.setenv("DATABASE_URL", url_de_pruebas)
    monkeypatch.delenv("CUOTA_EXENTAS", raising=False)
    base_de_datos.cerrar()
    _limpiar()
    yield
    _limpiar()
    base_de_datos.cerrar()


def _usuaria(correo=None):
    with base_de_datos.transaccion() as c:
        uid = c.execute(text("INSERT INTO usuarios (emisor, sub) VALUES (:e, :s) RETURNING id"),
                        {"e": EMISOR, "s": uuid.uuid4().hex}).scalar_one()
        if correo:
            c.execute(text("INSERT INTO usuario_emails (email, usuario_id, principal) VALUES (:m, :u, true)"),
                      {"m": correo, "u": uid})
    return uid


def _fila(unidades, *, usuario_id=None, estado="completada", cuando=MAYO, coste="0.01", real=True, tipo="cv"):
    with base_de_datos.transaccion() as c:
        c.execute(text("INSERT INTO gastos_generacion (usuario_id, tipo, modelo, unidades, estado, coste_estimado, "
                       "coste_real, creado_en) VALUES (:u, :t, :m, :n, :e, :c, :r, :w)"),
                  {"u": usuario_id, "t": tipo, "m": MODELO, "n": unidades, "e": estado, "c": coste,
                   "r": coste if real else None, "w": cuando})


def _gasto(importe, **kw):
    _fila(0, coste=str(importe), **kw)


def _filas(usuario_id=None):
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT tipo, unidades, estado, coste_estimado, coste_real FROM gastos_generacion "
                              "WHERE modelo = :m AND (CAST(:u AS uuid) IS NULL OR usuario_id = :u) "
                              "ORDER BY creado_en"), {"m": MODELO, "u": usuario_id}).all()


def _reservar(uid, tipo="cv", ahora=MAYO, largo=PROMPT, max_tokens=4096):
    return cuota.reservar(uid, tipo, largo, max_tokens=max_tokens, modelo=MODELO, ahora=ahora)


# --- the quota -------------------------------------------------------------------------------

def test_a_reservation_inserts_a_reservada_row_with_the_units_of_its_kind(bd):
    uid = _usuaria()
    cv, carta = _reservar(uid, "cv"), _reservar(uid, "carta")
    assert isinstance(cv, Reserva) and cv.unidades == Decimal("0.7") and cv.estimado_eur == ESTIMADO
    assert carta.unidades == Decimal("0.3")
    assert [(f.tipo, f.unidades, f.estado) for f in _filas(uid)] == [
        ("cv", Decimal("0.70"), "reservada"), ("carta", Decimal("0.30"), "reservada")]


def test_the_quota_boundary_is_exact_with_decimals(bd):
    uid = _usuaria()
    _fila("7.3", usuario_id=uid)
    assert isinstance(_reservar(uid, "cv"), Reserva)            # 7.3 + 0.7 = 8.0, allowed
    otra = _usuaria()
    _fila("7.4", usuario_id=otra)
    rechazo = _reservar(otra, "cv")                              # 7.4 + 0.7 = 8.1, refused
    assert rechazo == Rechazo("cuota", date(2032, 6, 1))
    assert isinstance(_reservar(otra, "carta"), Reserva)         # 7.4 + 0.3 = 7.7 still fits


def test_eight_full_applications_then_the_refusal_carries_the_reset_date(bd):
    uid = _usuaria()
    for _ in range(8):
        assert isinstance(_reservar(uid, "cv"), Reserva) and isinstance(_reservar(uid, "carta"), Reserva)
    assert _reservar(uid, "cv") == Rechazo("cuota", date(2032, 6, 1))
    assert _reservar(uid, "carta") == Rechazo("cuota", date(2032, 6, 1))
    assert len(_filas(uid)) == 16  # a refusal writes nothing


def test_the_month_boundary_is_utc(bd):
    uid = _usuaria()
    _fila("8", usuario_id=uid, cuando=datetime(2032, 5, 31, 23, 59, 59, tzinfo=timezone.utc))
    assert _reservar(uid, ahora=datetime(2032, 5, 31, 23, 59, 59, tzinfo=timezone.utc)).__class__ is Rechazo
    assert isinstance(_reservar(uid, ahora=datetime(2032, 6, 1, 0, 0, 0, tzinfo=timezone.utc)), Reserva)
    with base_de_datos.transaccion() as c:
        assert cuota.unidades_usadas(c, uid, datetime(2032, 6, 1, 0, 0, 1, tzinfo=timezone.utc)) == Decimal("0.7")
        assert cuota.unidades_usadas(c, uid, datetime(2032, 5, 31, 23, 59, 59, tzinfo=timezone.utc)) == Decimal("8")


def test_a_failed_generation_gives_the_units_back_but_keeps_its_cost(bd):
    uid = _usuaria()
    reserva = _reservar(uid, "cv")
    assert cuota.marcar_fallida(reserva.id) is True
    with base_de_datos.transaccion() as c:
        assert cuota.unidades_usadas(c, uid, MAYO) == 0
        assert cuota.gasto_del_mes(c, MAYO) == ESTIMADO     # coste_real stays NULL: the estimate counts
    assert _filas(uid)[0].coste_real is None


def test_completing_a_reservation_records_the_real_cost_and_keeps_the_units(bd):
    uid = _usuaria()
    reserva = _reservar(uid, "cv")
    assert cuota.marcar_completada(reserva.id, Decimal("0.0210"), 1500, 800) is True
    assert cuota.marcar_completada(reserva.id, Decimal("9"), 1, 1) is False   # already closed
    fila = _filas(uid)[0]
    assert (fila.estado, fila.coste_real) == ("completada", Decimal("0.0210"))
    with base_de_datos.transaccion() as c:
        assert cuota.unidades_usadas(c, uid, MAYO) == Decimal("0.7")
        assert cuota.gasto_del_mes(c, MAYO) == Decimal("0.0210")


def test_one_users_units_do_not_count_for_another(bd):
    a, b = _usuaria(), _usuaria()
    _fila("8", usuario_id=a)
    assert isinstance(_reservar(b), Reserva)


# --- the global cap --------------------------------------------------------------------------

def test_the_cap_refuses_when_spend_plus_the_estimate_passes_it(bd):
    uid = _usuaria()
    _gasto(Decimal("20") - ESTIMADO + Decimal("0.0001"))
    assert _reservar(uid) == Rechazo("tope", date(2032, 6, 1))
    assert _filas(uid) == []


def test_the_cap_admits_a_reservation_that_lands_exactly_on_it(bd):
    _gasto(Decimal("20") - ESTIMADO)
    assert isinstance(_reservar(_usuaria()), Reserva)


def test_orphan_rows_of_deleted_accounts_count_for_the_cap_and_deletion_cannot_reset_it(bd):
    uid = _usuaria()
    _gasto("19.99", usuario_id=uid)
    with base_de_datos.transaccion() as c:
        c.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": uid})
    assert _reservar(_usuaria()) == Rechazo("tope", date(2032, 6, 1))


def test_failed_rows_and_unclosed_reservations_count_their_estimate_for_the_cap(bd):
    uid = _usuaria()
    _gasto("10", usuario_id=uid, estado="fallida", real=False)
    _gasto("9.99", usuario_id=uid, estado="reservada", real=False)
    assert _reservar(uid) == Rechazo("tope", date(2032, 6, 1))


def test_the_quota_is_reported_before_the_cap_when_both_apply(bd):
    uid = _usuaria()
    _fila("8", usuario_id=uid, coste="20")
    assert _reservar(uid).motivo == "cuota"


def test_the_next_month_starts_the_cap_from_zero(bd):
    _gasto("20")
    assert isinstance(_reservar(_usuaria(), ahora=JUNIO), Reserva)


def test_the_cap_is_separate_from_the_extraction_ledger(bd):
    # A full extraction ledger must not touch the generation cap: different tables.
    with base_de_datos.transaccion() as c:
        c.execute(text("INSERT INTO extracciones (usuario_id, modelo, estado, estimado_eur, coste_eur, creada_en) "
                       "VALUES (NULL, :m, 'completada', 5, 5, :t)"), {"m": MODELO, "t": MAYO})
    try:
        assert isinstance(_reservar(_usuaria()), Reserva)
    finally:
        with base_de_datos.transaccion() as c:
            c.execute(text("DELETE FROM extracciones WHERE modelo = :m"), {"m": MODELO})


def _a_la_vez(url, n, trabajo):
    resultados, errores = [], []
    barrera = threading.Barrier(n)

    def correr(i):
        motor = base_de_datos.crear_motor(url)  # its own connection: real concurrency
        try:
            barrera.wait(timeout=20)
            with motor.begin() as conexion:
                resultados.append(trabajo(conexion, i))
        except Exception as error:
            errores.append(type(error).__name__)
        finally:
            motor.dispose()
    hilos = [threading.Thread(target=correr, args=(i,)) for i in range(n)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)
    assert errores == [] and len(resultados) == n
    return resultados


def test_two_concurrent_reservations_cannot_jointly_pass_the_cap(bd, url_de_pruebas):
    usuarias = [_usuaria() for _ in range(2)]
    _gasto(Decimal("20") - ESTIMADO)  # room for exactly one more estimate
    resultados = _a_la_vez(url_de_pruebas, 2, lambda c, i: cuota.reservar_en(
        c, usuarias[i], "cv", PROMPT, max_tokens=4096, modelo=MODELO, ahora=MAYO))
    assert sum(isinstance(r, Reserva) for r in resultados) == 1
    assert sum(r == Rechazo("tope", date(2032, 6, 1)) for r in resultados) == 1
    with base_de_datos.transaccion() as c:
        assert cuota.gasto_del_mes(c, MAYO) <= Decimal("20")


def test_ten_concurrent_reservations_with_room_for_one_make_exactly_one(bd, url_de_pruebas):
    usuarias = [_usuaria() for _ in range(10)]
    _gasto(Decimal("20") - ESTIMADO)
    resultados = _a_la_vez(url_de_pruebas, 10, lambda c, i: cuota.reservar_en(
        c, usuarias[i], "cv", PROMPT, max_tokens=4096, modelo=MODELO, ahora=MAYO))
    assert sum(isinstance(r, Reserva) for r in resultados) == 1


def test_concurrent_requests_of_one_user_cannot_jointly_pass_her_quota(bd, url_de_pruebas):
    uid = _usuaria()
    _fila("7.5", usuario_id=uid)  # room for one letter (0.3), not for two
    resultados = _a_la_vez(url_de_pruebas, 5, lambda c, i: cuota.reservar_en(
        c, uid, "carta", PROMPT, max_tokens=1500, modelo=MODELO, ahora=MAYO))
    assert sum(isinstance(r, Reserva) for r in resultados) == 1
    assert sum(isinstance(r, Rechazo) for r in resultados) == 4


# --- generar: the whole wrapper -------------------------------------------------------------------------

def _correo():
    return f"{uuid.uuid4().hex[:8]}@example.com"


def _generar(correo, llamar, tipo="cv", ahora=MAYO):
    return cuota.generar(correo, tipo, "x" * PROMPT, modelo=MODELO, max_tokens=4096, llamar=llamar, ahora=ahora)


def test_a_successful_call_is_closed_with_the_cost_of_the_reported_usage(bd):
    correo = _correo()
    uid = _usuaria(correo)
    respuesta = _generar(correo, lambda: RespuestaLLM("texto", MODELO, 2000, 900))
    assert respuesta.contenido == "texto"
    fila = _filas(uid)[0]
    assert fila.estado == "completada" and fila.coste_real == cuota.coste_real_eur(2000, 900)
    assert fila.coste_real < fila.coste_estimado


def test_an_answer_without_usage_is_closed_at_the_estimate(bd):
    correo = _correo()
    uid = _usuaria(correo)
    _generar(correo, lambda: RespuestaLLM("texto", "groq"))
    fila = _filas(uid)[0]
    assert fila.estado == "completada" and fila.coste_real == fila.coste_estimado == ESTIMADO


def test_a_failing_call_keeps_the_estimate_but_not_the_units_and_the_error_propagates(bd):
    correo = _correo()
    uid = _usuaria(correo)

    def cae():
        raise RuntimeError("Todos los LLMs fallaron")
    with pytest.raises(RuntimeError, match="Todos"):
        _generar(correo, cae)
    assert [f.estado for f in _filas(uid)] == ["fallida"]
    with base_de_datos.transaccion() as c:
        assert cuota.unidades_usadas(c, uid, MAYO) == 0
        assert cuota.gasto_del_mes(c, MAYO) == ESTIMADO


def test_a_bug_in_the_call_also_closes_the_reservation_as_failed(bd):
    correo = _correo()
    uid = _usuaria(correo)

    def bug():
        raise AttributeError("nuestro")
    with pytest.raises(AttributeError):
        _generar(correo, bug)
    assert [f.estado for f in _filas(uid)] == ["fallida"]


def test_over_quota_refuses_before_the_model_is_called(bd):
    correo = _correo()
    uid = _usuaria(correo)
    _fila("8", usuario_id=uid)
    llamadas = []
    with pytest.raises(cuota.Rechazada) as capturado:
        _generar(correo, lambda: llamadas.append(1))
    assert llamadas == [] and capturado.value.rechazo == Rechazo("cuota", date(2032, 6, 1))


def test_over_the_cap_refuses_before_the_model_is_called(bd):
    correo = _correo()
    _usuaria(correo)
    _gasto("20")
    llamadas = []
    with pytest.raises(cuota.Rechazada) as capturado:
        _generar(correo, lambda: llamadas.append(1))
    assert llamadas == [] and capturado.value.rechazo.motivo == "tope"


def test_an_unknown_mailbox_is_legacy_and_leaves_no_row(bd):
    llamadas = []
    _generar("nadie@example.com", lambda: llamadas.append(1) or RespuestaLLM("t", "m", 1, 1))
    assert llamadas == [1] and _filas() == []


def test_an_exempt_mailbox_with_a_neon_row_is_never_counted_or_blocked(bd, monkeypatch):
    correo = _correo()
    uid = _usuaria(correo)
    _fila("8", usuario_id=uid)
    _gasto("20")
    monkeypatch.setenv("CUOTA_EXENTAS", correo)
    llamadas = []
    _generar(correo, lambda: llamadas.append(1) or RespuestaLLM("t", "m", 1, 1))
    assert llamadas == [1] and len(_filas(uid)) == 1  # only the row the test planted


def test_exemption_follows_the_user_through_any_of_her_mailboxes(bd, monkeypatch):
    principal, alias = _correo(), _correo()
    uid = _usuaria(principal)
    with base_de_datos.transaccion() as c:
        c.execute(text("INSERT INTO usuario_emails (email, usuario_id) VALUES (:e, :u)"), {"e": alias, "u": uid})
    _fila("8", usuario_id=uid)
    monkeypatch.setenv("CUOTA_EXENTAS", principal)
    llamadas = []
    _generar(alias, lambda: llamadas.append(1) or RespuestaLLM("t", "m", 1, 1))
    assert llamadas == [1]


def test_a_database_failure_when_reserving_for_a_known_user_refuses_without_calling_the_model(bd, monkeypatch):
    from sqlalchemy.exc import OperationalError
    correo = _correo()
    _usuaria(correo)

    def cae(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("host secreto-db.internal refused"))
    monkeypatch.setattr(cuota, "reservar", cae)
    llamadas = []
    with pytest.raises(cuota.Rechazada) as capturado:
        _generar(correo, lambda: llamadas.append(1))
    assert llamadas == [] and capturado.value.rechazo.motivo == "indisponible"


def test_a_failure_while_closing_does_not_hide_a_good_answer(bd, monkeypatch):
    from sqlalchemy.exc import OperationalError
    correo = _correo()
    uid = _usuaria(correo)

    def cae(*args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception("secreto-db"))
    monkeypatch.setattr(cuota, "marcar_completada", cae)
    respuesta = _generar(correo, lambda: RespuestaLLM("texto", "m", 5, 5))
    assert respuesta.contenido == "texto"
    assert [f.estado for f in _filas(uid)] == ["reservada"]  # over-counts, never under-counts


# --- the state shown in /yo ---------------------------------------------------------------------------------

def test_the_state_reports_units_with_one_decimal_and_the_reset_date(bd):
    uid = _usuaria()
    _fila("0.7", usuario_id=uid)
    _fila("0.3", usuario_id=uid, tipo="carta")
    _fila("0.7", usuario_id=uid, estado="fallida")
    with base_de_datos.transaccion() as c:
        assert cuota.estado_de(c, uid, MAYO) == {"usadas": 1.0, "limite": 8.0, "se_renueva": "2032-06-01",
                                                    "tope_agotado": False}
    assert cuota.estado_de_usuaria(uid, "x@example.com", MAYO) == {"usadas": 1.0, "limite": 8.0,
                                                                   "se_renueva": "2032-06-01",
                                                    "tope_agotado": False}


def test_the_state_is_omitted_for_exempt_users_and_without_a_user(bd, monkeypatch):
    correo = _correo()
    uid = _usuaria(correo)
    assert cuota.estado_de_usuaria(None, correo) is None
    monkeypatch.setenv("CUOTA_EXENTAS", correo)
    assert cuota.estado_de_usuaria(uid, correo) is None


def test_the_state_is_omitted_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cuota.estado_de_usuaria("alguien", "a@example.com") is None


# --- the alarm ---------------------------------------------------------------------------------------------------

@pytest.fixture
def correos(bd, monkeypatch):
    enviados = []
    monkeypatch.setattr(cuota, "aviso_configurado", lambda: True)
    monkeypatch.setattr(cuota, "enviar_aviso", lambda mes, gasto, tope: enviados.append((mes, gasto, tope)))
    return enviados


def _marcas():
    with base_de_datos.transaccion() as c:
        return c.execute(text("SELECT mes FROM avisos_gasto WHERE mes >= '2032-01-01' AND mes < '2033-01-01' "
                              "ORDER BY mes")).scalars().all()


def test_below_70_percent_nothing_is_sent(bd, correos):
    _gasto("13.99")
    assert cuota.avisar_si_corresponde(MAYO) is False
    assert correos == [] and _marcas() == []


def test_at_70_percent_one_mail_goes_out_and_only_one_per_month(bd, correos):
    _gasto("14")
    assert cuota.avisar_si_corresponde(MAYO) is True
    _gasto("1")
    assert cuota.avisar_si_corresponde(MAYO) is False
    assert cuota.avisar_si_corresponde(MAYO) is False
    assert correos == [(date(2032, 5, 1), Decimal("14.0000"), Decimal("20"))]
    assert _marcas() == [date(2032, 5, 1)]


def test_a_new_month_may_send_its_own_mail(bd, correos):
    _gasto("14")
    _gasto("14", cuando=JUNIO)
    cuota.avisar_si_corresponde(MAYO)
    cuota.avisar_si_corresponde(JUNIO)
    assert [c[0] for c in correos] == [date(2032, 5, 1), date(2032, 6, 1)]


def test_a_failing_mail_never_raises_logs_only_the_type_and_is_retried_later(bd, monkeypatch, caplog):
    llamadas = []

    def cae(mes, gasto, tope):
        llamadas.append(1)
        raise ConnectionError("https://api.brevo.com/v3 api-key=xkeysib-secreta ana@example.com")
    monkeypatch.setattr(cuota, "aviso_configurado", lambda: True)
    monkeypatch.setattr(cuota, "enviar_aviso", cae)
    _gasto("15")
    with caplog.at_level(logging.DEBUG):
        assert cuota.avisar_si_corresponde(MAYO) is False
    assert "ConnectionError" in caplog.text
    assert "xkeysib" not in caplog.text and "brevo" not in caplog.text and "ana@example.com" not in caplog.text
    assert _marcas() == []                        # the marker was released: the next call retries
    monkeypatch.setattr(cuota, "enviar_aviso", lambda *a: llamadas.append("ok"))
    assert cuota.avisar_si_corresponde(MAYO) is True
    assert llamadas == [1, "ok"] and _marcas() == [date(2032, 5, 1)]


def test_without_configuration_nothing_is_sent_and_no_marker_is_left(bd, monkeypatch):
    monkeypatch.setattr(cuota, "aviso_configurado", lambda: False)
    _gasto("19")
    assert cuota.avisar_si_corresponde(MAYO) is False
    assert _marcas() == []


def test_concurrent_checks_send_one_mail(bd, url_de_pruebas, monkeypatch):
    enviados = []
    monkeypatch.setattr(cuota, "aviso_configurado", lambda: True)
    monkeypatch.setattr(cuota, "enviar_aviso", lambda *a: enviados.append(1))
    _gasto("15")
    resultados = _a_la_vez(url_de_pruebas, 5, lambda c, i: cuota.avisar_en(c, MAYO))
    assert sum(resultados) == 1


def test_generating_past_70_percent_sends_the_alarm_and_a_mail_failure_does_not_block(bd, monkeypatch):
    def cae(*args):
        raise TimeoutError("boom")
    monkeypatch.setattr(cuota, "aviso_configurado", lambda: True)
    monkeypatch.setattr(cuota, "enviar_aviso", cae)
    correo = _correo()
    uid = _usuaria(correo)
    _gasto("14")
    respuesta = _generar(correo, lambda: RespuestaLLM("texto", "m", 5, 5))
    assert respuesta.contenido == "texto" and [f.estado for f in _filas(uid)] == ["completada"]
