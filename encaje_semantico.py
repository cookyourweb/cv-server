"""Semantic fit between a profile and an offer: pure, no I/O.

It answers "how close is this offer to what I want?" (topic affinity). It is NOT
`match.py`, which answers "can I honestly apply?" from requirements (ADR-009).

Everything here only FLAGS: the margins between offers are thin (about +-0.025)
and salaries arrive as free text, so nothing is discarded automatically. Data that
cannot be parsed is "no data", never a reason.
"""
import math
import re
import unicodedata

UMBRAL_DUPLICADA = 0.95
MAX_TEXTO_OFERTA = 2000


# ─── Similarity ─────────────────────────────────────────────────────────────

def coseno(a: list[float], b: list[float]) -> float:
    """1.0 = same direction (same topic), 0 = unrelated. pgvector's `<=>` is 1 - this."""
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def puntuar(v_perfil: list[float], v_anti: list[float] | None, v_oferta: list[float]) -> float:
    """score = similarity to what I want - similarity to what I avoid.

    Without an anti-profile (empty `Evitar`) nothing is subtracted.
    """
    score = coseno(v_perfil, v_oferta)
    if v_anti is not None:
        score -= coseno(v_anti, v_oferta)
    return score


def es_duplicada(similitud: float, umbral: float = UMBRAL_DUPLICADA) -> bool:
    return similitud > umbral


# ─── Free-text salary ───────────────────────────────────────────────────────

_NUMERO = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(k\b)?")
_PARENTESIS = re.compile(r"\([^)]*\)")
# Words that may surround an annual EUR-ish figure. Anything else (hora, mes, prose
# like "pidió mín.") makes the text ambiguous.
_PALABRAS_OK = {"eur", "euro", "euros", "usd", "gbp", "bruto", "brutos", "ano", "anual",
                "anuales", "year", "yr", "annual", "gross", "al", "de"}


def _sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def parsear_salario_min(texto: str | None) -> int | None:
    """Lower bound of a free-text annual salary, as a bare number (no currency conversion).

    Rules (anything that breaks one returns None, never a guess):
    - Text in parentheses is ignored ("(equiv. $30-$150/hr)", "(tarifa orientativa)").
    - "k" multiplies by 1000: "35k" -> 35000, "62,5k" -> 62500.
    - "." or "," followed by exactly 3 digits is a thousands separator: "111.000" -> 111000.
      Combined with "k" it is nonsense ("62.500k") -> None.
    - A decimal without "k" ("45.5") is ambiguous -> None.
    - Every figure must be >= 1000 once resolved: "90-120k" has a bare "90" that could
      be 90 or 90k -> None. This also drops hourly rates and tiny numbers.
    - Words other than currency/annual markers (hora, mes, prose) -> None.
    - With several figures the lowest wins ("60.000 € - 90.000 €" -> 60000).
    """
    if not texto:
        return None
    t = _sin_acentos(_PARENTESIS.sub(" ", texto).lower())
    valores = []
    for m in _NUMERO.finditer(t):
        crudo, k = m.group(1), bool(m.group(2))
        agrupado = bool(re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", crudo))
        if agrupado:
            if k:
                return None
            valor = int(re.sub(r"[.,]", "", crudo))
        elif re.search(r"[.,]", crudo):
            if not k:
                return None
            valor = round(float(crudo.replace(",", ".")) * 1000)
        else:
            valor = int(crudo) * (1000 if k else 1)
        if valor < 1000:
            return None
        valores.append(valor)
    if not valores:
        return None
    resto = _NUMERO.sub(" ", t)
    palabras = re.findall(r"[a-z]+", resto)
    if any(p not in _PALABRAS_OK for p in palabras):
        return None
    return min(valores)


# ─── Hard rules (flag, never discard) ───────────────────────────────────────

_PRESENCIALES = {"presencial", "hibrido"}
_UBICACION_SIN_DATO = {"", "sin confirmar", "s/i", "n/a", "remoto"}
# Municipalities counted as "Madrid" for the Madrid user (the offer rarely says "Madrid").
_AREA_MADRID = {"alcobendas", "pozuelo", "las rozas", "majadahonda", "boadilla", "getafe",
                "leganes", "mostoles", "fuenlabrada", "alcorcon", "alcala de henares",
                "tres cantos", "san sebastian de los reyes", "rivas", "coslada", "torrejon", "valdemorillo"}


def _norm(s: str | None) -> str:
    return _sin_acentos((s or "").strip().lower())


def reglas_duras(oferta: dict, preferencias: dict) -> list[str]:
    """Reasons to flag an offer. Unknown data is never a reason.

    preferencias: Notion user profile (`salario_min`, `ciudad`).
    """
    motivos = []
    minimo = preferencias.get("salario_min")
    pedido = parsear_salario_min(oferta.get("salario"))
    if minimo and pedido is not None and pedido < minimo:
        motivos.append("salario_bajo")

    ciudad = _norm(preferencias.get("ciudad"))
    ubicacion = _norm(oferta.get("ubicacion"))
    if (ciudad and _norm(oferta.get("modalidad")) in _PRESENCIALES
            and ubicacion not in _UBICACION_SIN_DATO):
        # Notion may hold "Valdemorillo, Madrid": each comma-separated part is a place she accepts.
        lugares = [p.strip() for p in ciudad.split(",") if p.strip()]
        cerca = any(l in ubicacion for l in lugares) or (
            "madrid" in lugares and any(m in ubicacion for m in _AREA_MADRID))
        if not cerca:
            motivos.append("ubicacion")
    return motivos


# ─── Texts to embed ─────────────────────────────────────────────────────────

def texto_de_perfil(perfil: dict) -> str:
    """Profile text from the Notion user fields `perfil`, `rol`, `stack`."""
    partes = [perfil.get("perfil") or "", perfil.get("rol") or "", ", ".join(perfil.get("stack") or [])]
    return "\n".join(p.strip() for p in partes if p and p.strip())


def texto_de_oferta(oferta: dict) -> str:
    texto = f"{oferta.get('puesto') or ''} en {oferta.get('empresa') or ''}. {oferta.get('descripcion') or ''}"
    return texto[:MAX_TEXTO_OFERTA]
