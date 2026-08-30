"""¿El CV que acaba de salir está bien?

Esa pregunta no la responde ningún otro sitio del proyecto. Los 231 tests que
hay vigilan la INSTRUCCIÓN: que el prompt no pida dos párrafos, que el modelo no
esté retirado, que los guardrails estén registrados. Son canarios sobre la
configuración, y están bien. Pero un sistema con LLM puede tener toda la
configuración correcta y devolver un texto peor.

Los tres fallos de calidad de agosto de 2026 los cazó una persona leyendo:

  1. Un resumen de 180 palabras (Social You). El prompt pedía dos párrafos.
  2. La carta ignoró OCHO AÑOS de Azure cuando la oferta lo nombraba cinco
     veces, y escribió "Azure is the gap I am ready to close".
  3. Un CV con la empresa equivocada: "AppCast" no es un empleador, es la
     plataforma que distribuye el anuncio.

Ninguno dio error. Ese es el punto: **un fallo de IA no produce una excepción,
produce un resultado plausible y peor.**

═══ POR QUÉ ESTÁ PARTIDO EN DOS ═══

`evaluar()` es PURA: recibe el texto YA generado y devuelve los fallos. No llama
a ningún modelo. Es rápida, determinista y se prueba con textos fijos, así que
puede correr en cada commit.

Generar de verdad contra el LLM es otra cosa: cuesta dinero, tarda y no da dos
veces lo mismo. Eso va aparte y se lanza a mano.

Mezclar las dos capas es el error clásico: acabas con una suite lenta, cara e
inestable que se termina desactivando, y entonces no tienes evaluación ninguna.

═══ LO QUE ESTO **NO** ES ═══

No mide si el CV es bueno. Mide si incumple reglas que ya fallaron una vez.
Es una red contra la regresión, no un juez de calidad. Un texto sin fallos no
es un texto excelente: es un texto que no repite errores conocidos.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field


class Fallo(BaseModel):
    """Lo que la evaluación encontró en un texto generado.

    Mismo criterio que `guardrails.Aviso`: la forma se declara donde el dato
    cruza una frontera, y no se devuelven dicts sueltos que nadie valida.

    `extra="forbid"` para que un typo en un nombre de campo sea un error y no
    un campo nuevo que nadie lee.
    """

    model_config = ConfigDict(extra="forbid")

    regla: str
    """Qué regla se incumplió. Sirve para agrupar y para filtrar."""

    detalle: str
    """Qué pasó exactamente, en una frase que se pueda leer sin contexto."""


class Caso(BaseModel):
    """Una oferta real y lo que debe (y no debe) pasar con ella.

    Es un dato, no código: añadir un caso no obliga a tocar `evaluar()`.
    """

    model_config = ConfigDict(extra="forbid")

    nombre: str
    empresa: str
    oferta: str
    master: str
    """El CV master del que sale la verdad. Sin él no se puede exigir nada:
    lo que no está aquí, el sistema no puede decirlo sin inventar."""

    debe_aparecer: list[str] = Field(default_factory=list)
    """Fortalezas que la oferta pide Y el master respalda. Si faltan en el
    texto, la candidatura regala su mejor argumento."""

    no_debe_aparecer: list[str] = Field(default_factory=list)
    """Lo que no puede colarse: intermediarios, tecnologías que no ha usado."""

    max_palabras_resumen: int | None = None
    """Tope del bloque de resumen, si la regla aplica a este caso."""


# El resumen es el primer bloque, hasta el siguiente encabezado en mayúsculas.
_ENCABEZADOS_RESUMEN = ("PROFESSIONAL SUMMARY", "PERFIL PROFESIONAL")


def _bloque_resumen(texto: str) -> str | None:
    """El resumen, o None si el texto no trae uno reconocible."""
    for enc in _ENCABEZADOS_RESUMEN:
        i = texto.find(enc)
        if i < 0:
            continue
        resto = texto[i + len(enc):]
        # termina en el siguiente encabezado (línea en mayúsculas) o al final
        m = re.search(r"\n\s*[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ /&]{4,}\s*\n", resto)
        return resto[:m.start()] if m else resto
    return None


# Cómo se admite que algo no se sabe. Si una de estas expresiones acompaña a una
# fortaleza que el master SÍ respalda, el texto la está regalando.
#
# 30-ago-2026: la primera versión solo miraba si el término aparecía, y daba por
# buena la carta que decía "Azure is the gap I am ready to close" con ocho años de
# Azure detrás. Mencionar no es reivindicar, y presentar una fortaleza como hueco
# es peor que callarla: abre en la entrevista un frente que no existe.
_CARENCIA = re.compile(
    r"\b(gap|gaps|eager to learn|ready to learn|willing to learn|looking forward to learning"
    r"|no (?:hands-on |direct |professional )?experience|little experience|not yet"
    r"|brecha|hueco|carencia|dispuesta? a aprender|me gustar[ií]a aprender"
    r"|sin experiencia|poca experiencia|a[uú]n no)\b",
    re.IGNORECASE,
)


def _frase_de_carencia(texto: str, termino: str) -> str | None:
    """La frase donde `termino` aparece junto a una admisión de carencia, si la hay.

    Se mira frase a frase y no en todo el texto: "no tengo experiencia en Kubernetes,
    y ocho años de Azure" no debe marcar Azure. La cercanía es lo que da el sentido.
    """
    for frase in re.split(r"(?<=[.!?;\n])\s+", texto):
        if termino.lower() in frase.lower() and _CARENCIA.search(frase):
            return frase.strip()
    return None


def evaluar(texto: str, caso: Caso) -> list[Fallo]:
    """Los fallos del texto frente a lo que el caso exige. Lista vacía = limpio.

    Lanza `ValueError` si el caso exige algo que su propio master no respalda:
    eso no es un fallo del texto, es un caso mal escrito. Exigirlo sería pedirle
    al sistema que mienta, que es justo lo que los guardrails impiden.
    """
    for termino in caso.debe_aparecer:
        if termino.lower() not in caso.master.lower():
            raise ValueError(
                f"el caso '{caso.nombre}' exige '{termino}' y el master no lo respalda: "
                f"pedirlo sería pedir una invención"
            )

    fallos: list[Fallo] = []
    bajo = texto.lower()

    for termino in caso.debe_aparecer:
        if termino.lower() not in bajo:
            fallos.append(Fallo(
                regla="fortaleza-omitida",
                detalle=(f"la oferta de {caso.empresa} pide '{termino}' y el master lo "
                         f"respalda, pero el texto no lo menciona"),
            ))
        elif (frase := _frase_de_carencia(texto, termino)) is not None:
            fallos.append(Fallo(
                regla="fortaleza-como-carencia",
                detalle=(f"'{termino}' se presenta como carencia y el master lo respalda: "
                         f"«{frase}»"),
            ))

    for termino in caso.no_debe_aparecer:
        if termino.lower() in bajo:
            fallos.append(Fallo(
                regla="no-debe-aparecer",
                detalle=f"'{termino}' aparece en el texto y no debería",
            ))

    if caso.max_palabras_resumen is not None:
        bloque = _bloque_resumen(texto)
        if bloque is not None:
            n = len(bloque.split())
            if n > caso.max_palabras_resumen:
                fallos.append(Fallo(
                    regla="resumen-largo",
                    detalle=(f"el resumen tiene {n} palabras y el tope son "
                             f"{caso.max_palabras_resumen}"),
                ))

    return fallos


# ══════════════════════════════════════════════
# EL CATÁLOGO
# ══════════════════════════════════════════════
# Un caso por fallo real. Se añade uno cada vez que algo sale mal: así la
# evaluación crece con el sistema en vez de quedarse en la foto del día que se
# escribió. Es la misma convención que las reglas de `wf-check.mjs` en el
# repositorio `buscartrabajo`.

_MASTER_VERO = (
    "Verónica Serna Pérez. Frontend senior, más de 20 años. "
    "Ocho años con Azure en ALD/Ayvens: App Services, Storage, pipelines de despliegue. "
    "React, TypeScript, Vue.js, Node.js, Python. "
    "Sistemas con LLM en producción: cv-server, guardrails contra alucinación, "
    "cascada Groq/Gemini/Claude, ADR midiendo LiteLLM."
)


def casos_guardados() -> list[Caso]:
    """Los casos del catálogo. Cada uno viene de un fallo que ocurrió de verdad."""
    return [
        Caso(
            # 29-ago-2026. La oferta nombraba Azure cinco veces. La carta escribió
            # "Azure is the gap I am ready to close" con ocho años de Azure detrás.
            nombre="azure-fortaleza-omitida",
            empresa="Nerdio",
            oferta="Strong Azure experience required. Azure DevOps, Azure AD, App Services.",
            master=_MASTER_VERO,
            debe_aparecer=["Azure"],
        ),
        Caso(
            # 29-ago-2026. Cuatro ofertas archivadas como "AppCast", que es la
            # plataforma que distribuye el anuncio. Las empresas reales eran
            # Lodgify, Plain Concepts, Accenture y Fortra.
            nombre="appcast-intermediario",
            empresa="Lodgify",
            oferta="Senior AI Engineer. Python, LLM.",
            master=_MASTER_VERO,
            no_debe_aparecer=["AppCast", "E-Frontiers"],
        ),
        Caso(
            # 29-ago-2026, Social You. 180 palabras en dos párrafos densos porque
            # el prompt pedía `2 full paragraphs (4-6 lines each)`.
            nombre="resumen-social-you",
            empresa="Social You",
            oferta="Senior GenAI Engineer. LLM en producción, evaluación.",
            master=_MASTER_VERO,
            max_palabras_resumen=80,
        ),
    ]
