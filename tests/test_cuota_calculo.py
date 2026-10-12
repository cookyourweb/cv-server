"""cuota: the pure part (units, month boundaries, estimate, exemption, legacy mode, alarm mail).

Nothing here needs a database. The legacy tests also prove that the quota logic never touches one.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import base_de_datos
import cuota
import llm
from llm import RespuestaLLM


def _prohibir_la_base(monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("the database must not be touched")
    monkeypatch.setattr(base_de_datos, "transaccion", prohibido)
    monkeypatch.setattr(base_de_datos, "motor", prohibido)


# --- the numbers of the decision ------------------------------------------------------------------

def test_the_defaults_are_the_owner_decision():
    assert cuota.LIMITE_UNIDADES == Decimal("8")
    assert cuota.UNIDADES["cv"] == Decimal("0.7") and cuota.UNIDADES["carta"] == Decimal("0.3")
    assert cuota.UNIDADES["cv"] + cuota.UNIDADES["carta"] == 1  # one application
    assert cuota.TOPE_EUR == Decimal("20")
    assert cuota.UMBRAL_AVISO == Decimal("0.7")


def test_eight_applications_fit_exactly_and_the_ninth_cv_does_not():
    usadas = sum((cuota.UNIDADES["cv"] + cuota.UNIDADES["carta"]) for _ in range(8))
    assert usadas == cuota.LIMITE_UNIDADES
    assert usadas + cuota.UNIDADES["cv"] > cuota.LIMITE_UNIDADES


@pytest.mark.parametrize("nombre", ["CUOTA_SOLICITUDES_MES", "CUOTA_UNIDADES_CV", "TOPE_GENERACION_EUR"])
def test_a_bad_number_in_the_environment_is_refused(monkeypatch, nombre):
    monkeypatch.setenv(nombre, "ocho")
    with pytest.raises(ValueError, match=nombre):
        cuota._decimal_del_entorno(nombre, "1")


# --- the month, in UTC ------------------------------------------------------------------------

@pytest.mark.parametrize("ahora, esperado", [
    (datetime(2026, 10, 11, 12, tzinfo=timezone.utc), date(2026, 11, 1)),
    (datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc), date(2026, 11, 1)),
    (datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc), date(2026, 12, 1)),
    (datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc), date(2027, 1, 1)),
    # 23:30 at UTC-2 is already the next month in UTC.
    (datetime(2026, 10, 31, 23, 30, tzinfo=timezone(timedelta(hours=-2))), date(2026, 12, 1)),
])
def test_the_reset_date_is_the_first_day_of_the_next_utc_month(ahora, esperado):
    assert cuota.renovacion(ahora) == esperado


def test_a_naive_clock_is_refused():
    with pytest.raises(ValueError):
        cuota.renovacion(datetime(2026, 10, 11, 12))


# --- the estimate ---------------------------------------------------------------------------------

def test_the_estimate_bills_claude_and_groq_only_never_gemini(monkeypatch):
    monkeypatch.setattr(cuota, "PRECIOS_PRIMARIO_EUR_POR_MTOK", (Decimal("3"), Decimal("15")))
    monkeypatch.setattr(cuota, "PRECIOS_GROQ_EUR_POR_MTOK", (Decimal("1"), Decimal("2")))
    # An absurd Gemini price would blow the estimate up if Gemini were still billed.
    monkeypatch.setattr(cuota, "PRECIOS_GEMINI_EUR_POR_MTOK", (Decimal("4000"), Decimal("5000")), raising=False)
    monkeypatch.setattr(cuota, "MARGEN", Decimal("2"))
    entrada = 334  # ceil(1000 / 3)
    primario = (entrada * 3 + 1500 * 15)           # the call asked for 1500 output tokens
    groq = (entrada * 1 + 1500 * 2)                # Groq is asked for the same limit as Claude
    esperado = (Decimal(primario + groq) / 1_000_000 * 2).quantize(Decimal("0.0001"), rounding="ROUND_CEILING")
    assert cuota.estimar_eur(1000, max_tokens=1500) == esperado


def test_the_estimate_grows_with_the_prompt_and_with_max_tokens_and_rounds_up():
    assert cuota.estimar_eur(30_000, max_tokens=4096) > cuota.estimar_eur(3_000, max_tokens=4096) > 0
    assert cuota.estimar_eur(3_000, max_tokens=4096) > cuota.estimar_eur(3_000, max_tokens=1500)
    assert cuota.estimar_eur(3_000, max_tokens=4096).as_tuple().exponent == -4


def test_a_typical_cv_reservation_is_a_small_fraction_of_the_cap():
    assert cuota.estimar_eur(15_000, max_tokens=4096) < cuota.TOPE_EUR / 50


def test_the_real_cost_prices_the_reported_usage_at_the_primary_price_and_rounds_up(monkeypatch):
    monkeypatch.setattr(cuota, "PRECIOS_PRIMARIO_EUR_POR_MTOK", (Decimal("3"), Decimal("15")))
    assert cuota.coste_real_eur(1500, 300) == Decimal("0.0090")
    assert cuota.coste_real_eur(1, 1) == Decimal("0.0001")


def test_the_cost_of_an_answer_without_usage_is_the_estimate():
    reserva = cuota.Reserva("r", Decimal("0.2000"), Decimal("0.7"))
    sin_uso = RespuestaLLM("texto", "groq-modelo")
    assert cuota.coste_de(sin_uso, reserva) == (Decimal("0.2000"), None, None)
    con_uso = RespuestaLLM("texto", "claude", 1500, 300)
    coste, ti, to = cuota.coste_de(con_uso, reserva)
    assert (ti, to) == (1500, 300) and coste == cuota.coste_real_eur(1500, 300)


# --- the exemption list ---------------------------------------------------------------------------

def test_the_exempt_list_is_comma_separated_trimmed_and_case_insensitive(monkeypatch):
    monkeypatch.setenv("CUOTA_EXENTAS", " Vero@Example.com ,, otra@example.com ")
    assert cuota.exentas() == frozenset({"vero@example.com", "otra@example.com"})
    assert cuota.es_exenta("VERO@example.com ") is True
    assert cuota.es_exenta("ana@example.com") is False
    monkeypatch.delenv("CUOTA_EXENTAS")
    assert cuota.exentas() == frozenset() and cuota.es_exenta("vero@example.com") is False


# --- legacy mode and exemptions never touch the database -------------------------------------------

def _llamar_con_cuota(email, llamadas, respuesta=None):
    def llamar():
        llamadas.append(1)
        return respuesta or RespuestaLLM("texto", "m", 10, 10)
    return cuota.generar(email, "cv", "x" * 3000, modelo="m", max_tokens=4096, llamar=llamar)


def test_without_database_url_the_call_goes_through_and_nothing_is_read(monkeypatch):
    _prohibir_la_base(monkeypatch)
    llamadas = []
    resultado = _llamar_con_cuota("vero@example.com", llamadas)
    assert resultado.contenido == "texto" and llamadas == [1]


def test_without_database_url_a_failing_call_propagates_untouched(monkeypatch):
    _prohibir_la_base(monkeypatch)
    error = RuntimeError("Todos los LLMs fallaron")

    def llamar():
        raise error
    with pytest.raises(RuntimeError) as capturado:
        cuota.generar("vero@example.com", "cv", "x", modelo="m", max_tokens=1, llamar=llamar)
    assert capturado.value is error


def test_an_exempt_email_is_never_counted_even_with_a_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/x")
    monkeypatch.setenv("CUOTA_EXENTAS", "vero@example.com")
    _prohibir_la_base(monkeypatch)
    llamadas = []
    _llamar_con_cuota("Vero@Example.com", llamadas)
    assert llamadas == [1]


def test_a_blank_email_is_not_subject_to_the_quota(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/x")
    _prohibir_la_base(monkeypatch)
    llamadas = []
    _llamar_con_cuota("  ", llamadas)
    assert llamadas == [1]


def test_a_lookup_failure_degrades_to_legacy_like_the_master_source(monkeypatch, caplog):
    from sqlalchemy.exc import OperationalError
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/x")

    def cae(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("host secreto-db.internal refused"))
    monkeypatch.setattr(base_de_datos, "transaccion", cae)
    llamadas = []
    with caplog.at_level(logging.DEBUG):
        _llamar_con_cuota("ana@example.com", llamadas)
    assert llamadas == [1]
    assert "secreto-db" not in caplog.text and "ana@example.com" not in caplog.text


# --- the alarm mail ----------------------------------------------------------------------------------

class _PostFalso:
    def __init__(self, error=None):
        self.llamadas, self.error = [], error

    def __call__(self, url, **kwargs):
        self.llamadas.append((url, kwargs))
        if self.error:
            raise self.error
        return type("R", (), {"raise_for_status": lambda self: None})()


def test_the_alarm_goes_through_brevo_to_the_configured_address_without_logging_the_key(monkeypatch, caplog):
    monkeypatch.setenv("BREVO_API_KEY", "xkeysib-secreta")
    monkeypatch.setenv("BREVO_REMITENTE", "remitente@example.com")
    monkeypatch.setenv("AVISO_GASTO_EMAIL", "duena@example.com")
    post = _PostFalso()
    monkeypatch.setattr(cuota.requests, "post", post)
    with caplog.at_level(logging.DEBUG):
        cuota.enviar_aviso(date(2026, 10, 1), Decimal("14.2"), Decimal("20"))
    url, kw = post.llamadas[0]
    assert url == "https://api.brevo.com/v3/smtp/email"
    assert kw["headers"]["api-key"] == "xkeysib-secreta"
    assert kw["json"]["to"] == [{"email": "duena@example.com"}]
    assert kw["json"]["sender"] == {"email": "remitente@example.com"}
    assert kw["timeout"] <= 15
    assert "xkeysib-secreta" not in caplog.text


def test_the_alarm_is_not_configured_without_the_address_or_the_key(monkeypatch):
    monkeypatch.delenv("AVISO_GASTO_EMAIL", raising=False)
    monkeypatch.setenv("BREVO_API_KEY", "k")
    assert cuota.aviso_configurado() is False
    monkeypatch.setenv("AVISO_GASTO_EMAIL", "duena@example.com")
    monkeypatch.setenv("BREVO_REMITENTE", "remitente@example.com")
    assert cuota.aviso_configurado() is True
    monkeypatch.delenv("BREVO_API_KEY")
    assert cuota.aviso_configurado() is False


def test_llm_exposes_the_models_the_estimate_needs():
    # The estimate prices the general cascade; these are the ids it falls back to.
    assert llm.GROQ_MODEL and llm.GEMINI_MODEL and llm.CLAUDE_MODEL
