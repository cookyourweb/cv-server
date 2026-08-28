"""TDD - /health debe decir QUE MODELO escribe cada documento.

Caso real (27jul2026): tras cambiar CV_MODEL a Sonnet 4.6 en Render no habia forma
de confirmar el cambio desde fuera. /health devolvia constantes hardcodeadas:

    "llm_provider": "groq",  "version": "v2.3-groq"

...cuando los CVs los escribe `claude-haiku-4-5` (CV_MODEL) y las cartas
`claude-sonnet-4-6` (CARTA_MODEL). Groq es solo el FALLBACK si Claude falla.

Ya estaba documentado como contradiccion 12 en buscartrabajo/docs/10, con el mismo
patron que el bug de `modelo_usado` arreglado el 22jul: reportar una constante en
vez de lo que de verdad pasa. Un endpoint de salud que miente sobre su configuracion
es peor que no tenerlo: se toman decisiones con el.
"""
import server as srv


def _health():
    with srv.app.test_client() as c:
        return c.get("/health").get_json()


def test_health_responde_ok():
    assert _health()["status"] == "ok"


def test_declara_el_modelo_que_escribe_el_cv():
    assert _health()["modelos"]["cv"] == srv.CV_MODEL


def test_declara_el_modelo_que_escribe_la_carta():
    assert _health()["modelos"]["carta"] == srv.CARTA_MODEL


def test_declara_el_fallback():
    assert _health()["modelos"]["fallback"] == srv.GROQ_MODEL


def test_no_dice_que_el_proveedor_es_groq():
    # Groq es el FALLBACK. El proveedor primario de CV y carta es Claude.
    assert _health().get("llm_provider") != "groq"


def test_la_version_no_lleva_groq_pegado():
    # "v2.3-groq" describia una arquitectura que ya no es la real.
    assert "groq" not in _health()["version"].lower()


def test_sigue_informando_de_las_claves_configuradas():
    # No es una regresion: los fallbacks siguen siendo utiles para diagnosticar.
    assert "claude" in _health()["fallbacks"]
    assert "gemini" in _health()["fallbacks"]


def test_sigue_informando_del_deploy():
    assert "branch" in _health()["deploy"]
    assert "commit" in _health()["deploy"]
