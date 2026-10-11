"""Gates, spend ledger and kill switch for the owner-paid CV extraction (spec section 4).

The owner pays for ONE extraction per user at sign-up (ADR-004 amendment). Before any
model is called, `reservar` runs three gates in a fixed order and stops at the first one
that fails, reporting a `motivo` the panel turns into the manual form:

    1. desactivada  the kill switch: env EXTRACCION_ACTIVA=false (hard-off, read before
                    any database access), then the `ajustes.extraccion_activa` row
                    (read on every request, so it can be flipped without a redeploy).
                    A missing row counts as off: the switch fails closed.
    2. ya_usada     the user already has an extraction that is not `fallida`.
    3. tope         the UTC month's spend plus this reservation would pass TOPE_EUR.

The consent check (REQ-2.1) belongs to the route that calls this module.

Passing the gates inserts a `reservada` row holding a PESSIMISTIC estimate, inside the
same transaction that read the month's sum, under a global advisory lock. The lock makes
check-and-reserve atomic (REQ-4.8): concurrent requests queue, and each one sees the
rows the previous ones committed. A crash after the reservation over-counts and never
under-counts: the row stays `reservada` and its estimate stays in the sum.

The month's sum is `sum(coalesce(coste_eur, estimado_eur))` over every row, including the
anonymous ones left by deleted accounts (REQ-2.4): a completed call counts its real cost,
anything else counts its estimate. A `fallida` row (the whole provider chain failed) keeps
its estimate in the sum but does not use the user's attempt: the partial unique index of
`extracciones` ignores it, so she can retry later.

This module makes no model call (the route does, through `llm.call_llm_calidad`). The estimate covers the worst case of the quality chain
(primary model and, when it fails, the fallback), see `estimar_eur`.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from math import ceil

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import base_de_datos


def _decimal_del_entorno(nombre: str, defecto: str) -> Decimal:
    bruto = os.getenv(nombre, "").strip()
    try:
        valor = Decimal(bruto or defecto)
    except ArithmeticError:
        raise ValueError(f"{nombre} must be a number") from None
    if not valor.is_finite() or valor < 0:
        raise ValueError(f"{nombre} must be a finite number >= 0")
    return valor


# --- configuration ---------------------------------------------------------------------------------
# Monthly cap in EUR across ALL extractions (REQ-4.8).
TOPE_EUR = _decimal_del_entorno("TOPE_EXTRACCION_EUR", "5")

# Prices in EUR per million tokens, (input, output). They are list prices in USD used 1:1
# as EUR, which is already the safe side while the euro is worth more than the dollar,
# plus MARGEN on top. BEFORE ENABLING THE SWITCH in production, verify both against the
# providers' current price pages and the model ids the quality chain really uses
# (llm.CV_MODEL and llm.GROQ_MODEL).
PRECIOS_PRIMARIO_EUR_POR_MTOK = (
    _decimal_del_entorno("PRECIO_PRIMARIO_ENTRADA_EUR_POR_MTOK", "3"),
    _decimal_del_entorno("PRECIO_PRIMARIO_SALIDA_EUR_POR_MTOK", "15"),
)
PRECIOS_RESPALDO_EUR_POR_MTOK = (
    _decimal_del_entorno("PRECIO_RESPALDO_ENTRADA_EUR_POR_MTOK", "0.15"),
    _decimal_del_entorno("PRECIO_RESPALDO_SALIDA_EUR_POR_MTOK", "0.60"),
)
MARGEN = _decimal_del_entorno("MARGEN_EXTRACCION", "1.25")

TOKENS_SALIDA_MAX = 1200         # max_tokens of the call (C8 must send exactly this)
CARACTERES_POR_TOKEN = 3         # pessimistic: Spanish/English text is nearer 4
# Instructions plus CV text may not exceed this many characters (C8 cuts the CV to fit).
# It bounds one call to 0.05 USD at the primary prices above (amendment, S4.15).
MAX_CARACTERES_DE_PROMPT = 27_000

_CIEN_MIL = Decimal(1_000_000)
_PRECISION = Decimal("0.0001")   # numeric(8, 4) of the ledger
_CLAVE_DE_BLOQUEO = 7_342_501_904  # fixed bigint key of the advisory lock "tope_extraccion"
_APAGADO = {"false", "0", "no", "off"}


# --- results -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Reserva:
    id: object
    estimado_eur: Decimal


@dataclass(frozen=True)
class Rechazo:
    motivo: str  # "desactivada" | "ya_usada" | "tope"


# --- the estimate -------------------------------------------------------------------------------------------
def _coste_de_una_llamada(precios, largo_prompt: int) -> Decimal:
    entrada = ceil(max(largo_prompt, 0) / CARACTERES_POR_TOKEN)
    return (entrada * precios[0] + TOKENS_SALIDA_MAX * precios[1]) / _CIEN_MIL


def _a_precision_del_libro(importe: Decimal) -> Decimal:
    return importe.quantize(_PRECISION, rounding=ROUND_CEILING)  # always round UP


def estimar_primario_eur(largo_prompt: int) -> Decimal:
    """Upper bound of ONE call to the primary model (no margin)."""
    return _a_precision_del_libro(_coste_de_una_llamada(PRECIOS_PRIMARIO_EUR_POR_MTOK, largo_prompt))


def coste_real_eur(tokens_entrada: int, tokens_salida: int, *, primario: bool) -> Decimal:
    """Cost of a call from the usage the provider reported, at list prices (no margin).

    `primario` picks the primary or the fallback price list. Rounded up to the ledger's precision.
    """
    precios = PRECIOS_PRIMARIO_EUR_POR_MTOK if primario else PRECIOS_RESPALDO_EUR_POR_MTOK
    return _a_precision_del_libro((tokens_entrada * precios[0] + tokens_salida * precios[1]) / _CIEN_MIL)


def estimar_eur(largo_prompt: int) -> Decimal:
    """The pessimistic reservation for a prompt of `largo_prompt` characters.

    ceil(chars / 3) input tokens plus the maximum output tokens, priced for the primary
    model AND the fallback (the whole quality chain can bill), times the safety margin,
    rounded up to the ledger's precision.
    """
    peor_caso = (_coste_de_una_llamada(PRECIOS_PRIMARIO_EUR_POR_MTOK, largo_prompt)
                 + _coste_de_una_llamada(PRECIOS_RESPALDO_EUR_POR_MTOK, largo_prompt))
    return _a_precision_del_libro(peor_caso * MARGEN)


# --- the kill switch ------------------------------------------------------------------------------------------
def _apagada_por_entorno() -> bool:
    return os.getenv("EXTRACCION_ACTIVA", "").strip().lower() in _APAGADO


def _interruptor_encendido(c) -> bool:
    valor = c.execute(text("SELECT valor FROM ajustes WHERE clave = 'extraccion_activa'")).scalar_one_or_none()
    return valor is True  # absent, null, a string or false: off


def fijar_interruptor(conexion, activa: bool) -> None:
    """Turn the kill switch row on or off (used by PUT /ajustes/extraccion)."""
    conexion.execute(
        text("INSERT INTO ajustes (clave, valor) VALUES ('extraccion_activa', CAST(:v AS jsonb)) "
             "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"),
        {"v": "true" if activa else "false"})


# --- the ledger ---------------------------------------------------------------------------------------------------
def _en_utc(ahora):
    if ahora is None:
        return datetime.now(timezone.utc)
    if ahora.tzinfo is None:
        raise ValueError("the clock must be timezone-aware (UTC month boundaries)")
    return ahora.astimezone(timezone.utc)


def _limites_del_mes(ahora: datetime):
    inicio = datetime(ahora.year, ahora.month, 1, tzinfo=timezone.utc)
    siguiente = datetime(ahora.year + (ahora.month == 12), ahora.month % 12 + 1, 1, tzinfo=timezone.utc)
    return inicio, siguiente


def gasto_del_mes(conexion, ahora=None) -> Decimal:
    """Spend of the UTC month of `ahora`: real cost where known, the estimate otherwise."""
    inicio, fin = _limites_del_mes(_en_utc(ahora))
    return conexion.execute(
        text("SELECT coalesce(sum(coalesce(coste_eur, estimado_eur)), 0) FROM extracciones "
             "WHERE creada_en >= :ini AND creada_en < :fin"), {"ini": inicio, "fin": fin}).scalar_one()


def reservar_en(c, usuario_id, largo_prompt: int, *, modelo: str, ahora=None):
    """Run the gates inside the caller's transaction; the caller commits.

    Returns a `Reserva` (its row is inserted, and the advisory lock is held until the
    transaction ends) or a `Rechazo`. The lock is what makes the cap atomic: commit
    promptly after this returns.
    """
    ahora = _en_utc(ahora)
    if _apagada_por_entorno() or not _interruptor_encendido(c):
        return Rechazo("desactivada")
    if c.execute(text("SELECT 1 FROM extracciones WHERE usuario_id = :u AND estado <> 'fallida'"),
                 {"u": usuario_id}).first() is not None:
        return Rechazo("ya_usada")

    c.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CLAVE_DE_BLOQUEO})
    estimado = estimar_eur(largo_prompt)
    if gasto_del_mes(c, ahora) + estimado > TOPE_EUR:
        return Rechazo("tope")
    try:
        with c.begin_nested():
            fila = c.execute(
                text("INSERT INTO extracciones (usuario_id, modelo, estado, estimado_eur, creada_en) "
                     "VALUES (:u, :m, 'reservada', :e, :t) RETURNING id"),
                {"u": usuario_id, "m": modelo, "e": estimado, "t": ahora}).scalar_one()
    except IntegrityError:
        # A concurrent request of the same user got in first: the partial unique index says so.
        return Rechazo("ya_usada")
    return Reserva(fila, estimado)


def reservar(usuario_id, largo_prompt: int, *, modelo: str, ahora=None):
    """The gates in their own transaction, committed on return. See `reservar_en`.

    The environment hard-off is answered before the database is touched at all.
    """
    _en_utc(ahora)  # validates the clock before anything else
    if _apagada_por_entorno():
        return Rechazo("desactivada")
    with base_de_datos.transaccion() as c:
        return reservar_en(c, usuario_id, largo_prompt, modelo=modelo, ahora=ahora)


def marcar_completada(reserva_id, coste_eur: Decimal, tokens_entrada: int | None, tokens_salida: int | None) -> bool:
    """Close a reservation with its cost. False if it was not an open reservation.

    Tokens are None when the provider did not report its usage; the caller then passes the
    estimate as the cost, so the month's sum never under-counts.
    """
    with base_de_datos.transaccion() as c:
        return c.execute(
            text("UPDATE extracciones SET estado = 'completada', coste_eur = :c, tokens_entrada = :ti, "
                 "tokens_salida = :to WHERE id = :i AND estado = 'reservada'"),
            {"c": coste_eur, "ti": tokens_entrada, "to": tokens_salida, "i": reserva_id}).rowcount == 1


def marcar_fallida(reserva_id) -> bool:
    """Close a reservation whose provider chain failed.

    `coste_eur` stays NULL on purpose: the sum then counts the ESTIMATE, so a call that
    may have been billed never lowers the month's total. The user keeps her attempt.
    """
    with base_de_datos.transaccion() as c:
        return c.execute(
            text("UPDATE extracciones SET estado = 'fallida' WHERE id = :i AND estado = 'reservada'"),
            {"i": reserva_id}).rowcount == 1
