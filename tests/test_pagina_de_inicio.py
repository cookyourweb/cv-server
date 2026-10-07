"""La portada ya no es un formulario: es una pagina de invitacion.

El servicio es una beta privada. Quien llega a `/` no debe encontrar ningun
formulario ni ninguna llamada a rutas del servidor, solo como pedir acceso.
"""
import server as srv


def _portada():
    with srv.app.test_client() as c:
        return c.get("/")


def _cuerpo():
    return _portada().get_data(as_text=True)


def test_la_portada_responde_200():
    assert _portada().status_code == 200


def test_la_portada_no_tiene_formulario():
    cuerpo = _cuerpo().lower()
    for marca in ("<form", "<input", "fetch(", "<script"):
        assert marca not in cuerpo, f"la portada contiene {marca}"


def test_la_portada_no_llama_a_rutas_retiradas():
    cuerpo = _cuerpo()
    for ruta in ("/check-email", "/accion-existente", "/registro"):
        assert ruta not in cuerpo, f"la portada menciona {ruta}"


def test_la_portada_no_enlaza_a_usuarios():
    cuerpo = _cuerpo().lower()
    assert "/usuarios" not in cuerpo
    assert "<a " not in cuerpo


def test_la_portada_habla_de_invitacion():
    assert "invitaci" in _cuerpo().lower()
