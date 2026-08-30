"""TDD - medir si un CV generado esta BIEN, no solo si el sistema no revienta.

Caso real (30ago2026). `cv-server` tiene 231 tests y **ninguno mira el texto que
sale**. Todos vigilan la INSTRUCCION: que el prompt no pida dos parrafos, que el
modelo no este retirado, que los guardrails esten registrados. Son canarios sobre
la configuracion, y estan bien, pero no responden la pregunta que importa:

    ¿el CV que acabo de generar esta bien?

Los tres fallos de calidad de este mes los cazo una persona LEYENDO:

  1. Resumen de 180 palabras (Social You, 29ago). El prompt pedia dos parrafos.
  2. La carta ignoro OCHO ANOS de Azure cuando la oferta lo nombraba cinco veces,
     y escribio "Azure is the gap I am ready to close". Regalaba su mejor baza.
  3. Un CV salio con la empresa equivocada: "AppCast" no es un empleador, es la
     plataforma que distribuye el anuncio. La empresa real estaba en el cuerpo.

Ninguno dio error. Los tres produjeron un texto plausible y peor.

DISEÑO — dos capas, y la separacion es lo importante:

  · `evaluar()` es PURA: recibe el texto ya generado y devuelve los fallos. No
    llama a ningun modelo, asi que es rapida, determinista y se prueba con textos
    fijos. Es lo que se corre en cada commit.
  · Generar de verdad contra el LLM es OTRA cosa, cuesta dinero y no es
    determinista. Va aparte y se lanza a mano.

Mismo criterio que `guardrails.Aviso`: la forma se declara donde el dato cruza
una frontera, y `evaluar` devuelve una lista de `Fallo`, no dicts sueltos.
"""
import pytest

from evaluacion import Caso, Fallo, evaluar

MASTER = (
    "Veronica Serna Perez. Frontend senior, 20 anos. "
    "Ocho anos con Azure en ALD/Ayvens: pipelines, App Services, Storage. "
    "React, TypeScript, Python. Sistemas con LLM en produccion."
)

CASO_AZURE = Caso(
    nombre="oferta-que-pide-azure",
    empresa="Nerdio",
    oferta="We need strong Azure experience. Azure, Azure DevOps, Azure AD.",
    master=MASTER,
    debe_aparecer=["Azure"],
)


# ── la capa pura: mide el texto, no llama a nadie ────────────────────────────

def test_un_texto_correcto_no_da_fallos():
    texto = "PROFESSIONAL SUMMARY\nEight years with Azure at Ayvens. React and Python."
    assert evaluar(texto, CASO_AZURE) == []


def test_caza_la_fortaleza_relevante_que_falta():
    # El fallo 2: la oferta pide Azure, el master lo tiene, el texto lo calla.
    texto = "PROFESSIONAL SUMMARY\nFrontend engineer with React and Python."
    fallos = evaluar(texto, CASO_AZURE)
    assert fallos, "no vio que falta Azure"
    assert all(isinstance(f, Fallo) for f in fallos)
    assert any("azure" in f.detalle.lower() for f in fallos)


def test_caza_al_intermediario_colado_como_empresa():
    # El fallo 3: "AppCast" es la plataforma, no el empleador.
    caso = Caso(nombre="appcast", empresa="Lodgify", oferta="Senior AI Engineer",
                master=MASTER, no_debe_aparecer=["AppCast"])
    fallos = evaluar("Dear AppCast team, ...", caso)
    assert any("appcast" in f.detalle.lower() for f in fallos)


def test_caza_el_resumen_demasiado_largo():
    # El fallo 1: 180 palabras donde caben 80.
    caso = Caso(nombre="resumen-largo", empresa="Social You", oferta="GenAI",
                master=MASTER, max_palabras_resumen=80)
    largo = "PROFESSIONAL SUMMARY\n" + "palabra " * 180 + "\n\nEXPERIENCE\nAyvens"
    fallos = evaluar(largo, caso)
    assert any("resumen" in f.regla for f in fallos)
    assert not evaluar("PROFESSIONAL SUMMARY\nCorto y al grano.\n\nEXPERIENCE\nAyvens", caso)


def test_solo_exige_lo_que_el_master_respalda():
    # Si la oferta pide algo que la candidata NO tiene, exigirlo seria pedirle
    # al sistema que MIENTA. Eso es justo lo que los guardrails impiden.
    caso = Caso(nombre="pide-kubernetes", empresa="X",
                oferta="Kubernetes, Kubernetes, Kubernetes",
                master=MASTER, debe_aparecer=["Kubernetes"])
    with pytest.raises(ValueError, match="no lo respalda"):
        evaluar("Un CV cualquiera", caso)


# ── el catalogo de casos: son datos, no codigo ───────────────────────────────

def test_hay_casos_guardados_y_cubren_los_tres_fallos():
    from evaluacion import casos_guardados
    casos = casos_guardados()
    assert len(casos) >= 3, "el catalogo esta vacio"
    nombres = {c.nombre for c in casos}
    assert any("azure" in n for n in nombres)
    assert any("appcast" in n or "intermediario" in n for n in nombres)
    assert any("resumen" in n for n in nombres)


def test_cada_caso_guardado_es_coherente_consigo_mismo():
    # Un caso que exige algo que su propio master no respalda es un caso roto,
    # y hay que verlo al anadirlo, no seis meses despues.
    from evaluacion import casos_guardados
    for c in casos_guardados():
        for termino in c.debe_aparecer:
            assert termino.lower() in c.master.lower(), \
                f"caso '{c.nombre}': exige '{termino}' y su master no lo respalda"


# ── mencionar NO es reivindicar ──────────────────────────────────────────────
# 30ago2026. La primera version de `evaluar()` daba por bueno este texto:
#
#     "Azure is the gap I am ready to close"
#
# porque comprobaba si la palabra "Azure" aparecia, y aparece. Pero el fallo real
# era PEOR que omitirla: la carta presentaba como carencia algo que la candidata
# lleva OCHO ANOS haciendo. Regalaba su mejor baza y encima abria un frente que
# no hay que abrir.
#
# Se descubrio ensayando el evaluador contra el texto que fallo DE VERDAD. Un
# golden set que no se prueba contra los fallos reales solo mide lo que su autor
# imagino que podia salir mal.

TEXTOS_QUE_LA_PRESENTAN_COMO_CARENCIA = [
    "Azure is the gap I am ready to close.",
    "I am eager to learn Azure.",
    "I have no hands-on experience with Azure yet.",
    "Azure es una brecha que estoy dispuesta a cerrar.",
    "Estoy dispuesta a aprender Azure.",
]


@pytest.mark.parametrize("texto", TEXTOS_QUE_LA_PRESENTAN_COMO_CARENCIA)
def test_una_fortaleza_presentada_como_carencia_es_un_fallo(texto):
    fallos = evaluar(texto, CASO_AZURE)
    assert any(f.regla == "fortaleza-como-carencia" for f in fallos), \
        f"paso por bueno: {texto!r}"


def test_reivindicarla_de_verdad_no_da_fallo():
    # El contraste: aqui Azure se afirma como experiencia, no como hueco.
    texto = "Eight years building and deploying Azure App Services at Ayvens."
    assert evaluar(texto, CASO_AZURE) == []
