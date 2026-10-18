"""Batch semantic-fit score for the offers n8n created (ADR-011).

`puntuar_ofertas_core` is the Flask-independent core behind `POST /puntuar-ofertas`
(ADR-001: the route only delegates). For each active Notion user it scores her pending
offers and writes `Encaje` and `Avisos` back to Notion.

Privacy (ADR-010): her profile text goes to Gemini only when she is exempt
(`cuota.es_exenta`). Anybody else is skipped BEFORE any text is built. Logs carry counts
and exception class names, never profile, offer or error text.

Never creates a Neon account: without a Neon row (or without DATABASE_URL) the offer is
still scored and written to Notion, but its vector is not stored and duplicates are not
looked for (`sin_vectores`).
"""
import logging

import requests
from sqlalchemy.exc import SQLAlchemyError

import base_de_datos
import cuota
import embeddings
import encaje_semantico
import notion
import usuarias
import vectores

logger = logging.getLogger(__name__)

ESCALA = 1000   # +25, -13... instead of 0.025, -0.013


def _usuario_neon(emails):
    """Neon user id of a Notion user, or None (no database, no row, or database down)."""
    if not base_de_datos.configurada():
        return None
    try:
        with base_de_datos.transaccion() as conexion:
            return usuarias.id_por_emails(emails, conexion)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as e:
        logger.warning("puntuar: Neon user lookup failed (%s)", type(e).__name__)
        return None


def _guardar_y_buscar_duplicada(usuario_id, oferta, huella, vector) -> bool | None:
    """Look for a near-identical stored offer, then store this vector.

    True/False = duplicate found or not; None = the database failed (counts as sin_vectores).
    """
    try:
        with base_de_datos.transaccion() as conexion:
            parecida = vectores.mas_parecida(conexion, usuario_id, vector, oferta["page_id"])
            vectores.guardar(conexion, oferta["page_id"], usuario_id, embeddings.MODELO, huella, vector)
    except (SQLAlchemyError, base_de_datos.ErrorDeBaseDeDatos) as e:
        logger.warning("puntuar: storing a vector failed (%s)", type(e).__name__)
        return None
    return parecida is not None and encaje_semantico.es_duplicada(parecida[1])


def _puntuar_usuaria(usuaria: dict, balance: dict) -> None:
    try:
        ofertas = notion.ofertas_por_puntuar(usuaria["notion_id"])
    except requests.RequestException as e:
        logger.warning("puntuar: listing offers failed (%s)", type(e).__name__)
        balance["errores"] += 1
        return
    if not ofertas:
        return

    texto_perfil = encaje_semantico.texto_de_perfil(usuaria)
    if not texto_perfil:
        balance["errores"] += len(ofertas)
        return
    anti = (usuaria.get("evitar") or "").strip() or None
    textos_oferta = [encaje_semantico.texto_de_oferta(o) for o in ofertas]
    try:
        # One call per user: profile, optional anti-profile, then every offer.
        vs = embeddings.embeddings([texto_perfil] + ([anti] if anti else []) + textos_oferta)
    except Exception as e:  # Gemini, network or key: the batch of this user is lost, not the run
        logger.warning("puntuar: embeddings failed (%s)", type(e).__name__)
        balance["errores"] += len(ofertas)
        return
    v_perfil = vs[0]
    v_anti = vs[1] if anti else None
    v_ofertas = vs[2 if anti else 1:]

    usuario_id = _usuario_neon(usuaria.get("emails") or [usuaria.get("email", "")])
    for oferta, texto, vector in zip(ofertas, textos_oferta, v_ofertas):
        try:
            encaje = round(encaje_semantico.puntuar(v_perfil, v_anti, vector) * ESCALA)
            avisos = encaje_semantico.reglas_duras(oferta, usuaria)
            duplicada = None
            if usuario_id is not None:
                duplicada = _guardar_y_buscar_duplicada(
                    usuario_id, oferta, vectores.huella(texto), vector)
            if duplicada is None:
                balance["sin_vectores"] += 1
            elif duplicada:
                avisos.append("posible_duplicada")
            notion.escribir_encaje(oferta["page_id"], encaje, avisos)
            balance["puntuadas"] += 1
        except Exception as e:  # one offer never stops the batch
            logger.warning("puntuar: one offer failed (%s)", type(e).__name__)
            balance["errores"] += 1


def puntuar_ofertas_core() -> dict:
    """Score every exempt active user's pending offers.

    Raises requests.RequestException only when the user list itself cannot be read.
    `saltadas` counts users skipped because they are not exempt.
    """
    balance = {"puntuadas": 0, "saltadas": 0, "errores": 0, "sin_vectores": 0}
    for usuaria in notion.usuarios_activos():
        emails = usuaria.get("emails") or [usuaria.get("email", "")]
        if not any(cuota.es_exenta(e) for e in emails):
            balance["saltadas"] += 1
            continue
        _puntuar_usuaria(usuaria, balance)
    return {"ok": True, **balance}
