"""Honest rule-based match between a job offer and a candidate (C12).

PURE: no I/O, network, LLM or clock (tests/test_match.py enforces it by reading
the imports). The same input always gives the same output, it costs nothing and
every claim carries its evidence.

Rules (design "Honest match"):
- A technology is covered only if the CV master names it (guardrails' registry,
  word boundaries: Java != JavaScript). Evidence = first master line with it.
- Years of experience, language and work mode can be ELIMINATORY gaps.
- Soft skills and anything unknown go to `no_evaluables`: never guessed.
- Nothing the candidate says about motivation can turn a gap into covered; only
  the master counts. And this result never feeds the CV or letter generator
  (tests/test_match.py::test_REQ_6_3_match_never_reaches_the_generators).
"""
import re
from dataclasses import dataclass, field

import guardrails

# Reachable = no eliminatory gap AND coverage >= COBERTURA_MINIMA AND
# technology gaps <= MAX_HUECOS_TECNOLOGICOS (design wins over spec A7).
COBERTURA_MINIMA = 0.6
MAX_HUECOS_TECNOLOGICOS = 2
LARGO_EVIDENCIA = 160

_ANIOS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|anos)\b[^.\n]{0,40}?(?:experience|experiencia)")

_MODALIDADES = {
    "remoto": re.compile(r"\b(?:remote|remoto|teletrabajo)\b"),
    "hibrido": re.compile(r"\b(?:hybrid|hibrido)\b"),
    "presencial": re.compile(r"\b(?:on-?site|presencial|in-?office)\b"),
}

_IDIOMAS = {
    "en": ("english", "ingles", "en"),
    "es": ("spanish", "espanol", "castellano", "es"),
    "de": ("german", "aleman", "deutsch", "de"),
    "fr": ("french", "frances", "fr"),
    "pt": ("portuguese", "portugues", "pt"),
}
_NOMBRES_IDIOMA = "|".join(n for v in _IDIOMAS.values() for n in v if len(n) > 2)
_NIVEL = r"fluent|native|advanced|proficient|business level|fluido|nativo|avanzado|c1|c2"
_IDIOMA_EXIGIDO = (
    re.compile(rf"\b(?:{_NIVEL})\s+(?:in\s+|en\s+)?({_NOMBRES_IDIOMA})\b"),
    re.compile(rf"\b({_NOMBRES_IDIOMA})\s*\(?\s*(?:{_NIVEL})\b"),
)

# Soft skills: reported as not evaluable, never as covered or missing.
_BLANDAS = {
    "comunicacion": ("comunicacion", "communication"),
    "trabajo en equipo": ("trabajo en equipo", "teamwork", "team player"),
    "liderazgo": ("liderazgo", "leadership"),
    "proactividad": ("proactivo", "proactividad", "proactive"),
    "autonomia": ("autonomia", "autonomy", "self-starter"),
    "resolucion de problemas": ("resolucion de problemas", "problem solving", "problem-solving"),
}


@dataclass
class Encaje:
    cubiertos: list = field(default_factory=list)       # [{requisito, evidencia}]
    huecos: list = field(default_factory=list)          # [{requisito, eliminatorio}]
    no_evaluables: list = field(default_factory=list)   # [str]
    alcanzable: bool = False
    cobertura: float = 0.0
    tecnologias_pedidas: int = 0
    tecnologias_cubiertas: int = 0
    tecnologias_hueco: list = field(default_factory=list)

    def a_dict(self) -> dict:
        """The shape that goes out over HTTP (REQ-6.5)."""
        return {"cubiertos": self.cubiertos, "huecos": self.huecos,
                "no_evaluables": self.no_evaluables, "alcanzable": self.alcanzable,
                "cobertura": self.cobertura}


def _evidencia(master: str, tecnologia: str) -> str:
    for linea in master.splitlines():
        if tecnologia in guardrails._tecnologias_en(linea):
            return linea.strip()[:LARGO_EVIDENCIA]
    return ""


def _codigos_idioma(nombres) -> set:
    codigos = set()
    for n in nombres or []:
        n = guardrails._plano(str(n)).strip()
        for codigo, variantes in _IDIOMAS.items():
            if n in variantes:
                codigos.add(codigo)
    return codigos


def _anios(e: Encaje, plano: str, perfil: dict) -> None:
    pedidos = [int(m.group(1)) for m in _ANIOS.finditer(plano)]
    if not pedidos:
        return
    pedido = max(pedidos)
    requisito = f"{pedido}+ años de experiencia"
    propios = perfil.get("anios_experiencia")
    if not isinstance(propios, int) or isinstance(propios, bool):
        e.no_evaluables.append(requisito)
    elif propios < pedido:
        e.huecos.append({"requisito": requisito, "eliminatorio": True})
    else:
        e.cubiertos.append({"requisito": requisito, "evidencia": f"Perfil: {propios} años de experiencia"})


def _modalidad(e: Encaje, plano: str, perfil: dict) -> None:
    pedidas = {m for m, patron in _MODALIDADES.items() if patron.search(plano)}
    propias = set(perfil.get("modalidad") or [])
    if pedidas and propias and not pedidas & propias:
        e.huecos.append({"requisito": "modalidad: " + "/".join(sorted(pedidas)), "eliminatorio": True})


def _idiomas(e: Encaje, plano: str, perfil: dict) -> None:
    exigidos = set()
    for patron in _IDIOMA_EXIGIDO:
        for m in patron.finditer(plano):
            exigidos |= _codigos_idioma([m.group(1)])
    if not exigidos:
        return
    propios = _codigos_idioma(perfil.get("idiomas"))
    for codigo in sorted(exigidos):
        requisito = f"idioma: {codigo}"
        if not propios:
            e.no_evaluables.append(requisito)
        elif codigo not in propios:
            e.huecos.append({"requisito": requisito, "eliminatorio": True})


def evaluar(oferta_texto, perfil, master_texto) -> Encaje:
    """Compare an offer with the candidate. Never raises on empty or None."""
    oferta, master = oferta_texto or "", master_texto or ""
    perfil = perfil if isinstance(perfil, dict) else {}
    e = Encaje()
    plano = guardrails._plano(oferta)

    pedidas = sorted(guardrails._tecnologias_en(oferta))
    respaldadas = guardrails._tecnologias_en(master)
    for tec in pedidas:
        if tec in respaldadas:
            e.cubiertos.append({"requisito": tec, "evidencia": _evidencia(master, tec)})
            e.tecnologias_cubiertas += 1
        else:
            e.huecos.append({"requisito": tec, "eliminatorio": False})
            e.tecnologias_hueco.append(tec)
    e.tecnologias_pedidas = len(pedidas)

    _anios(e, plano, perfil)
    _modalidad(e, plano, perfil)
    _idiomas(e, plano, perfil)

    for nombre, variantes in _BLANDAS.items():
        if any(v in plano for v in variantes):
            e.no_evaluables.append(nombre)

    if pedidas:
        e.cobertura = round(e.tecnologias_cubiertas / len(pedidas), 4)
    # No technology named -> nothing to confirm -> not reachable (conservative).
    e.alcanzable = bool(
        pedidas
        and not any(h["eliminatorio"] for h in e.huecos)
        and e.cobertura >= COBERTURA_MINIMA
        and len(e.tecnologias_hueco) <= MAX_HUECOS_TECNOLOGICOS
    )
    return e
