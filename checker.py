"""Checker del CV maestro: contrato de diagnóstico, sin auto-completado."""

import io
import re
import unicodedata

from dataclasses import asdict, dataclass
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
REGLAS_VERSION = 2

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
    """Detecta secciones esperadas que faltan en el CV normalizado."""
    presentes = set()
    for key in normalizado.get("secciones_presentes", []):
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

    current = "general"
    top = current  # last level 1-2 heading: it also owns the content of its subsections
    sections[current] = []

    for line in texto.splitlines():
        if line.strip().startswith("#"):
            marcas = line.strip()
            nivel = len(marcas) - len(marcas.lstrip("#"))
            current = marcas.lstrip("#").strip().lower() or "general"
            sections.setdefault(current, [])
            if nivel <= 2:
                top = current
        else:
            sections.setdefault(current, []).append(line)
            if top != current:
                sections.setdefault(top, []).append(line)

    sections_normalizadas = {}
    for name, lines in sections.items():
        sections_normalizadas[name] = "\n".join(lines).strip()

    return {
        "texto_normalizado": "\n".join(texto.split()).strip(),
        "secciones": sections_normalizadas,
        "secciones_presentes": sorted(
            key for key, value in sections_normalizadas.items() if value
        ),
        "experiencias": [],
        "skills": [],
        "fechas": [],
    }


def _parsear_intervalos_anios(texto: str) -> list[tuple[int, int]]:
    intervalos: list[tuple[int, int]] = []
    meses = (r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|"
             r"diciembre|january|february|march|april|may|june|july|august|september|october|november|"
             r"december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|dic|ene|abr|ago)\.?")
    patron = re.compile(
        r"(19\d{2}|20\d{2})(?:\s*[-–—]\s*(?:" + meses + r"\s+)?(19\d{2}|20\d{2}|presente|actualidad|current|present))?",
        re.IGNORECASE)

    for match in patron.finditer(texto or ""):
        start = int(match.group(1))
        end_raw = match.group(2) or match.group(1)

        if str(end_raw).lower() in {"presente", "actualidad", "current", "present"}:
            import datetime

            end = datetime.datetime.now().year
        else:
            end = int(end_raw)

        if start > end:
            start, end = end, start
        intervalos.append((start, end))

    return intervalos


def detectar_gaps_temporales(texto: str, umbral_meses: int = 6) -> list[str]:
    """Detecta huecos mayores a `umbral_meses` entre intervalos de años."""
    intervalos = sorted(_parsear_intervalos_anios(texto))
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
    for (start_prev, end_prev), (start_next, end_next) in zip(merged, merged[1:]):
        gap_meses = (start_next - end_prev) * 12
        if gap_meses > umbral_meses:
            hallazgos.append(
                f"gap temporal de {gap_meses} meses aproximados entre {end_prev} y {start_next}"
            )

    return hallazgos


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
