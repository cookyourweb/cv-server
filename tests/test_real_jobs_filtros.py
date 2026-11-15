"""Tests for the per-user filters ported from n8n (spec 009, T4)."""
import real_jobs as rj


def test_tiene_keyword_ia_detecta_ai():
    oferta = {"puesto": "AI Engineer", "tags": [], "descripcion": ""}
    assert rj.tiene_keyword_ia(oferta) is True


def test_tiene_keyword_ia_sin_keyword():
    oferta = {"puesto": "Java Backend Developer", "tags": [], "descripcion": "Spring Boot"}
    assert rj.tiene_keyword_ia(oferta) is False


def test_filtrar_por_perfil_mantiene_ia_sin_stack():
    ofertas = [
        {"puesto": "AI Engineer", "tags": [], "descripcion": "LLM", "modalidad": "Remoto", "ubicacion": "Remote"},
        {"puesto": "Java Dev", "tags": [], "descripcion": "Spring", "modalidad": "Remoto", "ubicacion": "Remote"},
    ]
    out = rj.filtrar_por_perfil(ofertas, stack_usuario=["React"], min_matches_stack=1)
    puestos = [o["puesto"] for o in out]
    assert "AI Engineer" in puestos
    assert "Java Dev" not in puestos


def test_filtrar_por_modalidad_hibrido_ocasional():
    ofertas = [{"puesto": "Dev", "modalidad": "Híbrido", "ubicacion": "Barcelona, ES", "tags": [], "descripcion": ""}]
    out = rj.filtrar_por_modalidad(ofertas, modalidad_usuario=["hibrido"], ciudad_usuario="Madrid",
                                    ciudades_hibrido=["Barcelona"])
    assert len(out) == 1
    assert "notas" in out[0]
    assert "HIBRIDO BARCELONA" in out[0]["notas"]


def test_filtrar_por_modalidad_descarta_hibrido_no_aceptado():
    ofertas = [{"puesto": "Dev", "modalidad": "Híbrido", "ubicacion": "Malaga, ES", "tags": [], "descripcion": ""}]
    out = rj.filtrar_por_modalidad(ofertas, modalidad_usuario=["hibrido"], ciudad_usuario="Madrid",
                                    ciudades_hibrido=["Barcelona"])
    assert out == []


def test_aplicar_evitar_descarta():
    ofertas = [{"puesto": "Java Developer", "tags": [], "descripcion": ""}]
    out = rj.aplicar_evitar(ofertas, evitar="java")
    assert out == []


def test_region_remota_compatible():
    assert rj.region_remota_compatible("Worldwide", [], "Madrid") is True
    assert rj.region_remota_compatible("USA only", ["Spain"], "Madrid") is False
    assert rj.region_remota_compatible("Spain", ["Spain"], "Madrid") is True