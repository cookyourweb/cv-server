"""Quota and global cap of the owner-paid CV and cover letter generation (ADR-010).

Invited users generate on the owner's AI keys, inside two limits:

    quota   8 "applications" per user and UTC month. A tailored CV costs 0.7 units and a
            cover letter 0.3, so a CV plus its letter is exactly 1 (all configurable).
    cap     20 EUR per UTC month across ALL users, separate from the 5 EUR extraction cap
            of `extraccion.py` (another table, another advisory lock).

Both are checked BEFORE any model is called, in one transaction under a global advisory
lock, so check-and-reserve is atomic: concurrent requests queue and each one sees the rows
the previous ones committed. The reservation row holds a PESSIMISTIC estimate (prompt at 3
characters per token plus the output limit, for the primary model AND the whole fallback
cascade of `llm.call_llm_calidad`, times a margin). A crash after the reservation over-counts
and never under-counts.

Closing the row:
- `completada`: the real cost from the usage the provider reported (the estimate when it
  reported none, never a made-up zero).
- `fallida`: the call raised. The user gets her UNITS back (a failed generation is not her
  application) but the cost keeps counting at the estimate, because the call may have been
  billed. Same rule as the extraction ledger.

The monthly cap sums `coalesce(coste_real, coste_estimado)` over every row, including the
anonymous ones left by deleted accounts (`usuario_id` is set to NULL, not deleted): deleting
an account cannot reset the cap.

Who is subject: only a user who has a row in Neon. NOT subject, and never counted or
blocked, with no database access where it can be avoided:
- no DATABASE_URL (legacy mode),
- an email listed in CUOTA_EXENTAS, or any mailbox of a user that has one of them,
- a mailbox with no Neon user (the owner's legacy flow: Notion + Drive).
If the lookup itself fails the call goes through as legacy, like `fuente_master` does; once the
user is identified, a failing reservation REFUSES (`indisponible`) rather than spend unmetered.

The 70 % alarm sends ONE mail per month through Brevo; a failure is logged by type only and
never blocks a generation.
"""
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import ceil
from typing import Callable, Optional

import requests
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import base_de_datos
import extraccion
import fuente_master
from extraccion import _a_precision_del_libro, _decimal_del_entorno, _en_utc, _limites_del_mes
from privacidad import registrar_fallo

logger = logging.getLogger(__name__)

# --- configuration ---------------------------------------------------------------------------
LIMITE_UNIDADES = _decimal_del_entorno("CUOTA_SOLICITUDES_MES", "8")
UNIDADES = {
    "cv": _decimal_del_entorno("CUOTA_UNIDADES_CV", "0.7"),
    "carta": _decimal_del_entorno("CUOTA_UNIDADES_CARTA", "0.3"),
}
TOPE_EUR = _decimal_del_entorno("TOPE_GENERACION_EUR", "20")
UMBRAL_AVISO = _decimal_del_entorno("AVISO_GASTO_UMBRAL", "0.7")
MARGEN = _decimal_del_entorno("MARGEN_GENERACION", "1.25")

# EUR per million tokens, (input, output). The primary and Groq lists are the extraction's
# (PRECIO_PRIMARIO_* / PRECIO_RESPALDO_*). Gemini has its own; the Claude fallback of the general
# cascade is billed at the primary list (the safe side: it is Haiku by default).
PRECIOS_PRIMARIO_EUR_POR_MTOK = extraccion.PRECIOS_PRIMARIO_EUR_POR_MTOK
PRECIOS_GROQ_EUR_POR_MTOK = extraccion.PRECIOS_RESPALDO_EUR_POR_MTOK
PRECIOS_GEMINI_EUR_POR_MTOK = (
    _decimal_del_entorno("PRECIO_GEMINI_ENTRADA_EUR_POR_MTOK", "0.30"),
    _decimal_del_entorno("PRECIO_GEMINI_SALIDA_EUR_POR_MTOK", "2.50"),
)
PRECIOS_CLAUDE_RESPALDO_EUR_POR_MTOK = extraccion.PRECIOS_PRIMARIO_EUR_POR_MTOK

TOKENS_SALIDA_CASCADA = 4096     # llm.CascadaCasera asks every fallback for 4096 output tokens
CARACTERES_POR_TOKEN = extraccion.CARACTERES_POR_TOKEN
_CIEN_MIL = Decimal(1_000_000)
_CLAVE_DE_BLOQUEO = 7_342_501_905  # fixed bigint key of the advisory lock "tope_generacion"
_URL_BREVO = "https://api.brevo.com/v3/smtp/email"


# --- results ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Reserva:
    id: object
    estimado_eur: Decimal
    unidades: Decimal


@dataclass(frozen=True)
class Rechazo:
    motivo: str                           # "cuota" | "tope" | "indisponible"
    se_renueva: Optional[date] = None     # first day of the next UTC month


class Rechazada(Exception):
    """Raised by `generar` BEFORE any model is called. Carries the `Rechazo`."""

    def __init__(self, rechazo: Rechazo):
        super().__init__(rechazo.motivo)
        self.rechazo = rechazo


# --- dates, estimate, cost ---------------------------------------------------------------------
def renovacion(ahora: Optional[datetime] = None) -> date:
    """First day of the next UTC month: when quota and cap start from zero."""
    return _limites_del_mes(_en_utc(ahora))[1].date()


def _coste_de_una_llamada(precios, largo_prompt: int, tokens_salida: int) -> Decimal:
    entrada = ceil(max(largo_prompt, 0) / CARACTERES_POR_TOKEN)
    return (entrada * precios[0] + tokens_salida * precios[1]) / _CIEN_MIL


def estimar_eur(largo_prompt: int, *, max_tokens: int) -> Decimal:
    """The pessimistic reservation for a prompt of `largo_prompt` characters.

    The primary model (output limited to `max_tokens`) plus EVERY provider of the fallback
    cascade (Groq, Gemini, Claude; each asked for 4096 output tokens), times the margin,
    rounded up to the ledger's precision.
    """
    peor = _coste_de_una_llamada(PRECIOS_PRIMARIO_EUR_POR_MTOK, largo_prompt, max_tokens)
    for precios in (PRECIOS_GROQ_EUR_POR_MTOK, PRECIOS_GEMINI_EUR_POR_MTOK, PRECIOS_CLAUDE_RESPALDO_EUR_POR_MTOK):
        peor += _coste_de_una_llamada(precios, largo_prompt, TOKENS_SALIDA_CASCADA)
    return _a_precision_del_libro(peor * MARGEN)


def coste_real_eur(tokens_entrada: int, tokens_salida: int) -> Decimal:
    """Cost of a call from the usage the provider reported, at the primary list price."""
    return _a_precision_del_libro(
        (tokens_entrada * PRECIOS_PRIMARIO_EUR_POR_MTOK[0] + tokens_salida * PRECIOS_PRIMARIO_EUR_POR_MTOK[1])
        / _CIEN_MIL)


def coste_de(respuesta, reserva: Reserva):
    """(cost, tokens in, tokens out) of an answered call; the estimate when no usage was reported."""
    if respuesta.tokens_entrada is None or respuesta.tokens_salida is None:
        return reserva.estimado_eur, None, None
    return coste_real_eur(respuesta.tokens_entrada, respuesta.tokens_salida), \
        respuesta.tokens_entrada, respuesta.tokens_salida


# --- who is exempt -----------------------------------------------------------------------------
def exentas() -> frozenset:
    """Emails in CUOTA_EXENTAS (comma-separated, case-insensitive). Read on every call."""
    return frozenset(p.strip().lower() for p in os.getenv("CUOTA_EXENTAS", "").split(",") if p.strip())


def es_exenta(email: str) -> bool:
    return (email or "").strip().lower() in exentas()


def _usuaria_exenta(c, usuario_id) -> bool:
    lista = sorted(exentas())
    if not lista:
        return False
    return c.execute(text("SELECT 1 FROM usuario_emails WHERE usuario_id = :u AND email = ANY(:l)"),
                     {"u": usuario_id, "l": lista}).first() is not None


# --- the ledger ----------------------------------------------------------------------------------
def gasto_del_mes(conexion, ahora=None) -> Decimal:
    """Spend of the UTC month of `ahora`: real cost where known, the estimate otherwise."""
    inicio, fin = _limites_del_mes(_en_utc(ahora))
    return conexion.execute(
        text("SELECT coalesce(sum(coalesce(coste_real, coste_estimado)), 0) FROM gastos_generacion "
             "WHERE creado_en >= :ini AND creado_en < :fin"), {"ini": inicio, "fin": fin}).scalar_one()


def unidades_usadas(conexion, usuario_id, ahora=None) -> Decimal:
    """Units the user consumed in the UTC month: every row but the failed ones."""
    inicio, fin = _limites_del_mes(_en_utc(ahora))
    return conexion.execute(
        text("SELECT coalesce(sum(unidades), 0) FROM gastos_generacion WHERE usuario_id = :u "
             "AND estado <> 'fallida' AND creado_en >= :ini AND creado_en < :fin"),
        {"u": usuario_id, "ini": inicio, "fin": fin}).scalar_one()


def reservar_en(c, usuario_id, tipo: str, largo_prompt: int, *, max_tokens: int, modelo: str, ahora=None):
    """Run the gates inside the caller's transaction; the caller commits.

    Returns a `Reserva` (row inserted; the advisory lock is held until the transaction ends)
    or a `Rechazo`. Order: quota (about her), then cap (about everybody).
    """
    ahora = _en_utc(ahora)
    unidades = UNIDADES[tipo]
    c.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CLAVE_DE_BLOQUEO})
    renueva = renovacion(ahora)
    if unidades_usadas(c, usuario_id, ahora) + unidades > LIMITE_UNIDADES:
        return Rechazo("cuota", renueva)
    estimado = estimar_eur(largo_prompt, max_tokens=max_tokens)
    if gasto_del_mes(c, ahora) + estimado > TOPE_EUR:
        return Rechazo("tope", renueva)
    fila = c.execute(
        text("INSERT INTO gastos_generacion (usuario_id, tipo, modelo, unidades, estado, coste_estimado, creado_en) "
             "VALUES (:u, :t, :m, :n, 'reservada', :e, :w) RETURNING id"),
        {"u": usuario_id, "t": tipo, "m": modelo, "n": unidades, "e": estimado, "w": ahora}).scalar_one()
    return Reserva(fila, estimado, unidades)


def reservar(usuario_id, tipo: str, largo_prompt: int, *, max_tokens: int, modelo: str, ahora=None):
    """The gates in their own transaction, committed on return. See `reservar_en`."""
    _en_utc(ahora)  # validates the clock before anything else
    with base_de_datos.transaccion() as c:
        return reservar_en(c, usuario_id, tipo, largo_prompt, max_tokens=max_tokens, modelo=modelo, ahora=ahora)


def marcar_completada(reserva_id, coste_eur: Decimal, tokens_entrada: Optional[int],
                      tokens_salida: Optional[int]) -> bool:
    """Close a reservation with its cost. False if it was not an open reservation."""
    with base_de_datos.transaccion() as c:
        return c.execute(
            text("UPDATE gastos_generacion SET estado = 'completada', coste_real = :c, tokens_entrada = :ti, "
                 "tokens_salida = :to WHERE id = :i AND estado = 'reservada'"),
            {"c": coste_eur, "ti": tokens_entrada, "to": tokens_salida, "i": reserva_id}).rowcount == 1


def marcar_fallida(reserva_id) -> bool:
    """Close a reservation whose call failed: `coste_real` stays NULL so the estimate keeps counting,
    and the row stops counting as units."""
    with base_de_datos.transaccion() as c:
        return c.execute(
            text("UPDATE gastos_generacion SET estado = 'fallida' WHERE id = :i AND estado = 'reservada'"),
            {"i": reserva_id}).rowcount == 1


# --- the state shown to the user ---------------------------------------------------------------------
def _una_decima(valor: Decimal) -> float:
    return float(valor.quantize(Decimal("0.1")))


def estado_de(conexion, usuario_id, ahora=None) -> dict:
    """{usadas, limite, se_renueva}: units with one decimal, the reset date as ISO yyyy-mm-dd."""
    return {"usadas": _una_decima(unidades_usadas(conexion, usuario_id, ahora)),
            "limite": _una_decima(LIMITE_UNIDADES),
            "se_renueva": renovacion(ahora).isoformat()}


def estado_de_usuaria(usuario_id, email: str, ahora=None) -> Optional[dict]:
    """The `cuota` field of GET /yo, or None (omitted) for legacy, exempt or unknown users.

    Never raises: a database failure just omits the field.
    """
    if usuario_id is None or not base_de_datos.configurada() or es_exenta(email):
        return None
    try:
        with base_de_datos.transaccion() as c:
            if _usuaria_exenta(c, usuario_id):
                return None
            return estado_de(c, usuario_id, ahora)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        registrar_fallo(logger, "quota state unavailable", error)
        return None


# --- the 70 % alarm -----------------------------------------------------------------------------------
def aviso_configurado() -> bool:
    return all(os.getenv(v, "").strip() for v in ("AVISO_GASTO_EMAIL", "BREVO_API_KEY", "BREVO_REMITENTE"))


def enviar_aviso(mes: date, gasto: Decimal, tope: Decimal) -> None:
    """Mail the owner through Brevo. Raises on any failure; the caller logs the TYPE only."""
    porcentaje = (gasto / tope * 100) if tope else Decimal(0)
    cuerpo = (f"El gasto de generacion de CV y cartas de {mes:%Y-%m} ha llegado a {gasto:.2f} EUR, "
              f"el {porcentaje:.0f} % del tope de {tope:.2f} EUR. "
              "Al llegar al tope se bloquea la generacion para todas hasta el mes siguiente.")
    respuesta = requests.post(
        _URL_BREVO,
        headers={"api-key": os.getenv("BREVO_API_KEY", "").strip(), "accept": "application/json",
                 "content-type": "application/json"},
        json={"sender": {"email": os.getenv("BREVO_REMITENTE", "").strip()},
              "to": [{"email": os.getenv("AVISO_GASTO_EMAIL", "").strip()}],
              "subject": "Aviso: gasto de generacion al 70 % del tope mensual",
              "textContent": cuerpo},
        timeout=10)
    respuesta.raise_for_status()


def avisar_en(c, ahora=None) -> bool:
    """Send the month's alarm if the spend reached the threshold and it was not sent yet.

    The marker row is inserted and the mail sent inside one savepoint: concurrent callers wait
    on the marker, exactly one sends, and a failed mail releases the marker so a later call
    retries. Returns True only when THIS call sent the mail. Never raises for a mail failure.
    """
    if not aviso_configurado():
        return False
    ahora = _en_utc(ahora)
    gasto = gasto_del_mes(c, ahora)
    if gasto < TOPE_EUR * UMBRAL_AVISO:
        return False
    mes = _limites_del_mes(ahora)[0].date()
    try:
        with c.begin_nested():
            reclamado = c.execute(
                text("INSERT INTO avisos_gasto (mes) VALUES (:m) ON CONFLICT (mes) DO NOTHING RETURNING mes"),
                {"m": mes}).first() is not None
            if not reclamado:
                return False
            enviar_aviso(mes, gasto, TOPE_EUR)
    except Exception as error:  # the savepoint rolled back: the marker is free again
        registrar_fallo(logger, "spend alarm not sent", error)
        return False
    return True


def avisar_si_corresponde(ahora=None) -> bool:
    """`avisar_en` in its own transaction. Swallows everything: it must never block a generation."""
    if not aviso_configurado():
        return False
    try:
        with base_de_datos.transaccion() as c:
            return avisar_en(c, ahora)
    except Exception as error:
        registrar_fallo(logger, "spend alarm check failed", error)
        return False


# --- the wrapper the generation routes use ---------------------------------------------------------------
def _usuaria_sujeta(email: str):
    """The user id when this mailbox belongs to a non-exempt Neon user; otherwise None (legacy)."""
    correo = (email or "").strip().lower()
    if not base_de_datos.configurada() or not correo or correo in exentas():
        return None
    try:
        with base_de_datos.transaccion() as c:
            usuario_id = fuente_master.usuario_id_por_email(c, correo)
            if usuario_id is None or _usuaria_exenta(c, usuario_id):
                return None
            return usuario_id
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        registrar_fallo(logger, "quota lookup unavailable", error)
        return None


def _cerrar(accion, *args) -> None:
    """Close a reservation without ever hiding the generation's own outcome."""
    try:
        accion(*args)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        registrar_fallo(logger, "generation ledger not closed", error)  # stays `reservada`: over-counts


def generar(email: str, tipo: str, prompt: str, *, modelo: str, max_tokens: int,
            llamar: Callable, ahora=None):
    """Run `llamar()` (the model call) inside the quota and cap of the user behind `email`.

    Not subject (legacy, exempt, unknown mailbox): just `llamar()`, nothing counted, no
    exception altered. Subject: reserve first (`Rechazada` BEFORE the model on a refusal),
    then close the row with the real cost, or as failed if `llamar` raised (re-raised as is).
    """
    usuario_id = _usuaria_sujeta(email)
    if usuario_id is None:
        return llamar()
    try:
        reserva = reservar(usuario_id, tipo, len(prompt), max_tokens=max_tokens, modelo=modelo, ahora=ahora)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as error:
        registrar_fallo(logger, "quota reservation unavailable", error)
        raise Rechazada(Rechazo("indisponible")) from None
    if isinstance(reserva, Rechazo):
        raise Rechazada(reserva)

    cerrada = False
    try:
        respuesta = llamar()
        coste, tokens_entrada, tokens_salida = coste_de(respuesta, reserva)
        _cerrar(marcar_completada, reserva.id, coste, tokens_entrada, tokens_salida)
        cerrada = True
    finally:
        if not cerrada:
            _cerrar(marcar_fallida, reserva.id)
        avisar_si_corresponde(ahora)  # a failed call's estimate counts too
    return respuesta
