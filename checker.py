"""Checker del CV maestro: contrato de diagnóstico, sin auto-completado."""

import io
import re
import unicodedata

from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from typing import Any

CLAIM_INDICATORS = (
    "mejoré", "mejoro", "optimicé", "optimice", "reduje", "reduzco",
    "aumenté", "aumente", "ahorré", "ahorro", "lideré", "lidere",
    "aceleré", "acelero", "impacto",
)

SKILL_HEADINGS = {
    "skills", "habilidades", "tecnologias", "tecnologías",
    "tech stack", "stack", "stack tecnologico", "stack tecnológico",
}


SECTIONS_CANONICAL = {
    "experiencia": "experiencia",
    "experience": "experiencia",
    "experiencias": "experiencia",
    "habilidades": "habilidades",
    "habilidades tecnicas": "habilidades",
    "skills": "habilidades",
    "formacion": "educacion",
    "educacion": "educacion",
    "education": "educacion",
    "proyectos": "proyectos",
    "projects": "proyectos",
}

# Bump when detector rules change: invalidates cached analyses.
# 3 (18-nov-2026): gaps with month names; sections detected by heading, not by body.
REGLAS_VERSION = 3

SECCIONES_RECUPERABLES = {"experiencia", "habilidades", "educacion", "proyectos"}


def _normalizar_encabezado(texto: str) -> str:
    """Lowercase, no accents, no emoji/symbols: "💼 EXPERIENCIA LABORAL" -> "experiencia laboral"."""
    sin_tildes = "".join(
        ch for ch in unicodedata.normalize("NFD", texto or "") if unicodedata.category(ch) != "Mn"
    ).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sin_tildes).split())


def _seccion_canonica(encabezado: str) -> str | None:
    clave = _normalizar_encabezado(encabezado)
    if clave in SECTIONS_CANONICAL:
        return SECTIONS_CANONICAL[clave]
    for palabra, canonica in SECTIONS_CANONICAL.items():
        if re.search(rf"\b{re.escape(palabra)}\b", clave):
            return canonica
    return None


def detectar_secciones_recuperables(normalizado: dict[str, Any]) -> list[str]:
    """Detecta secciones esperadas que faltan en el CV normalizado.

    Mira los encabezados que aparecen, no si la seccion tiene lineas propias. Un CV
    real escribe "## EXPERIENCIA LABORAL" y cuelga todo de subencabezados
    ("### 1. Empresa A"); entonces la seccion se quedaba vacia y se reportaba como
    ausente aunque estuviera escrita (detectado con tests/test_checker_cv_master_real).
    """
    claves = normalizado.get("encabezados")
    if claves is None:
        claves = normalizado.get("secciones_presentes", [])

    presentes = set()
    for key in claves:
        canonica = _seccion_canonica(key)
        if canonica:
            presentes.add(canonica)

    return sorted(SECCIONES_RECUPERABLES - presentes)


def tiene_metrica(texto: str) -> bool:
    return bool(re.search(r"\d", texto or ""))


def detectar_claims_sin_metrica(texto: str) -> list[str]:
    """Devuelve claims que afirman impacto pero no incluyen una métrica."""
    hallazgos: list[str] = []
    for line in (texto or "").splitlines():
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if any(ind in lower for ind in CLAIM_INDICATORS) and not tiene_metrica(line):
            hallazgos.append(line)
    return hallazgos


def _normalizar_texto(texto: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(ch) != "Mn"
    ).lower()


def _tokens_significativos(texto: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9+#.-]+", _normalizar_texto(texto)) if len(token) >= 2]


def _esta_presente(probe: str, evidence: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(probe)}(?![a-z0-9])", evidence) is not None


def detectar_skills_sin_evidencia(texto: str) -> list[str]:
    """Detecta skills declaradas sin evidencia en la experiencia u otras secciones."""
    normalizado = normalizar_cv(texto or "")
    secciones = normalizado["secciones"]

    skill_text = ""
    for heading, content in secciones.items():
        if heading in SKILL_HEADINGS:
            skill_text = f"{skill_text}\n{content}"

    if not skill_text.strip():
        return []

    evidence = _normalizar_texto(
        "\n".join(content for heading, content in secciones.items() if heading not in SKILL_HEADINGS and content.strip())
    )

    skills = []
    for chunk in skill_text.splitlines():
        for item in chunk.split(","):
            skill = item.strip().strip("- ").strip()
            if skill:
                skills.append(skill)

    findings: list[str] = []
    for skill in skills:
        tokens = _tokens_significativos(skill)
        supported = any(_esta_presente(token, evidence) for token in tokens)
        if tokens and not supported:
            findings.append(skill)

    findings_unicos = []
    for finding in findings:
        if finding not in findings_unicos:
            findings_unicos.append(finding)
    return findings_unicos


class Status(str, Enum):
    OK = "ok"
    WARNING = "warning"
    INSUFFICIENT_CONTENT = "insufficient-content"


@dataclass
class Finding:
    type: str
    message: str
    evidence: str | None = None


@dataclass
class Proposal:
    type: str
    message: str
    section: str | None = None


@dataclass
class AnalysisResult:
    status: Status
    findings: list[Finding]
    proposals: list[Proposal]
    hash_cv: str
    version_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "findings": [asdict(f) for f in self.findings],
            "proposals": [asdict(p) for p in self.proposals],
            "hash_cv": self.hash_cv,
            "version_label": self.version_label,
        }


def normalizar_pdf_a_texto(pdf_bytes: bytes) -> str:
    """Extrae texto de un PDF. Devuelve ValueError si el PDF no es legible."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf no esta disponible en el entorno") from exc

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        paginas = []
        for pagina in reader.pages:
            paginas.append(pagina.extract_text() or "")
        return "\n".join(paginas).strip()
    except Exception as exc:
        raise ValueError("No se pudo leer el PDF") from exc


def normalizar_cv(texto: str) -> dict[str, Any]:
    """Convierte texto o Markdown a una estructura mínima."""
    texto = (texto or "").strip()
    sections = {}
    encabezados: list[str] = []

    current = "general"
    sections[current] = []

    def canonicalizar_titulo(titulo: str) -> str:
        lower = titulo.strip().lstrip("#").strip().lower()
        if "experiencia" in lower:
            return "experiencia"
        if any(term in lower for term in ("skills", "habilidades", "tecnolog", "tech stack", "stack")):
            return "habilidades"
        if any(term in lower for term in ("educacion", "education", "formacion", "academic")):
            return "educacion"
        if any(term in lower for term in ("proyectos", "projects", "portfolio")):
            return "proyectos"
        if any(term in lower for term in ("perfil", "summary", "resumen", "objective")):
            return "perfil"
        if any(term in lower for term in ("logros", "impacto", "hitos")):
            return "logros"
        return lower or "general"

    for line in texto.splitlines():
        encabezado = None
        raw = line.strip()
        if raw.startswith("#"):
            encabezado = raw.lstrip("#").strip()
        elif raw and raw.isupper() and len(raw) <= 60 and len(raw.split()) <= 8:
            encabezado = raw
        if encabezado is not None:
            current = canonicalizar_titulo(encabezado)
            encabezados.append(current)
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)

    sections_normalizadas = {}
    for name, lines in sections.items():
        sections_normalizadas[name] = "\n".join(lines).strip()

    return {
        "texto_normalizado": "\n".join(texto.split()).strip(),
        "secciones": sections_normalizadas,
        "secciones_presentes": sorted(
            key for key, value in sections_normalizadas.items() if value
        ),
        # Encabezados vistos, tengan contenido propio o no. `secciones_presentes`
        # responde a "¿hay algo escrito?" (CV vacio); `encabezados`, a "¿esta la
        # seccion?". Un CV real suele colgar el contenido de subencabezados.
        "encabezados": sorted(set(encabezados)),
        "experiencias": [],
        "skills": [],
        "fechas": [],
    }


def extraer_contenido_minimo(normalizado: dict[str, Any]) -> set[str]:
    """Devuelve las secciones relevantes para evaluar contenido suficiente."""
    return {
        key
        for key in normalizado["secciones_presentes"]
        if key in {"experiencia", "experiencias", "skills", "habilidades", "experience", "skills list"}
    }

import json
from pathlib import Path


def _analisis_a_dict(analysis):
    if hasattr(analysis, "to_dict"):
        return analysis.to_dict()
    return dict(analysis)


def _directorio_analisis(storage_dir=None):
    if storage_dir:
        return Path(storage_dir)
    return Path(__file__).resolve().parent / "data" / "cv_checker"


def persistir_analisis(hash_cv: str, analysis, storage_dir=None) -> dict:
    directorio = _directorio_analisis(storage_dir)
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / f"{hash_cv}.json"

    if ruta.exists():
        guardado = json.loads(ruta.read_text(encoding="utf-8"))
        if guardado.get("reglas_version") == REGLAS_VERSION:
            return guardado
        # Stale: produced by older detector rules, recompute.

    payload = _analisis_a_dict(analysis)
    payload["hash_cv"] = hash_cv
    payload["reglas_version"] = REGLAS_VERSION
    ruta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def obtener_analisis_por_hash(hash_cv: str, storage_dir=None):
    ruta = _directorio_analisis(storage_dir) / f"{hash_cv}.json"
    if not ruta.exists():
        return None
    return json.loads(ruta.read_text(encoding="utf-8"))


_MESES = {
    "enero": 1, "ene": 1, "january": 1, "jan": 1,
    "febrero": 2, "feb": 2, "february": 2,
    "marzo": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "april": 4, "apr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6, "june": 6,
    "julio": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "septiembre": 9, "setiembre": 9, "sept": 9, "sep": 9, "september": 9,
    "octubre": 10, "oct": 10, "october": 10,
    "noviembre": 11, "nov": 11, "november": 11,
    "diciembre": 12, "dic": 12, "december": 12, "dec": 12,
}

_FINALES_ABIERTOS = ("actualidad", "presente", "actual", "hoy", "current", "present", "now")

_MES_RE = "|".join(sorted((re.escape(m) for m in _MESES), key=len, reverse=True))
_FIN_RE = "|".join(sorted((re.escape(f) for f in _FINALES_ABIERTOS), key=len, reverse=True))
_INICIO_RE = rf"(?:(?P<mes>{_MES_RE})\b\.?\s+(?:de\s+)?)?(?P<anio>(?:19|20)\d{{2}})"
_RANGO_RE = re.compile(
    rf"{_INICIO_RE}(?:\s*(?:[-–—]|\ba\b|\bal\b|\bto\b|\bhasta\b)\s*"
    rf"(?:(?:(?P<mes_fin>{_MES_RE})\b\.?\s+(?:de\s+)?)?(?P<anio_fin>(?:19|20)\d{{2}})|(?P<actual>{_FIN_RE})))?",
    re.IGNORECASE,
)


def _indice_mes(anio: int, mes: int) -> int:
    return anio * 12 + (mes - 1)


def _parsear_intervalos_meses(texto: str) -> list[tuple[int, int]]:
    """Intervalos (inicio, fin) en meses absolutos: 2025-05 -> 2025*12+4.

    Acepta nombres de mes en español e inglés y los finales abiertos
    ("Actualidad", "Presente", "Present"), que antes se leían como un año suelto.
    Un año suelto ("2002") cubre el año entero; una fecha suelta, doce meses.
    """
    intervalos: list[tuple[int, int]] = []
    hoy = date.today()

    for match in _RANGO_RE.finditer(texto or ""):
        mes_inicio = _MESES.get((match.group("mes") or "").lower(), 1)
        inicio = _indice_mes(int(match.group("anio")), mes_inicio)

        if match.group("actual"):
            fin = _indice_mes(hoy.year, hoy.month)
        elif match.group("anio_fin"):
            mes_fin = _MESES.get((match.group("mes_fin") or "").lower(), 12)
            fin = _indice_mes(int(match.group("anio_fin")), mes_fin)
        else:
            fin = inicio + 11

        if inicio > fin:
            inicio, fin = fin, inicio
        intervalos.append((inicio, fin))

    return intervalos


def _etiqueta_mes(indice: int) -> str:
    anio, mes = divmod(indice, 12)
    return f"{anio}-{mes + 1:02d}"


def detectar_gaps_temporales(texto: str, umbral_meses: int = 12) -> list[str]:
    """Detecta huecos de mas de `umbral_meses` entre intervalos de fechas.

    Con nombres de mes el hueco se mide en meses, pero menos de un año no se
    reporta: entre "Septiembre 2016" y "Junio 2017" hay nueve meses, que es un
    cambio de trabajo normal, no un hueco que merezca un aviso al usuario.
    """
    intervalos = sorted(_parsear_intervalos_meses(texto))
    if len(intervalos) < 2:
        return []

    merged: list[tuple[int, int]] = [intervalos[0]]
    for start, end in intervalos[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    hallazgos: list[str] = []
    for (_, end_prev), (start_next, _) in zip(merged, merged[1:]):
        gap_meses = start_next - end_prev - 1
        if gap_meses > umbral_meses:
            hallazgos.append(
                f"gap temporal de {gap_meses} meses entre {_etiqueta_mes(end_prev)} y {_etiqueta_mes(start_next)}"
            )

    return hallazgos
