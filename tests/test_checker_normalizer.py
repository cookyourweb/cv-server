from checker import normalizar_cv


def test_normaliza_markdown():
    texto = """
# Experiencia
Senior Developer en ACME 2022-2024

## Resultados
Redujo costes 20%

# Skills
Python, FastAPI
"""
    salida = normalizar_cv(texto)

    assert "experiencia" in salida["secciones"]
    assert "habilidades" in salida["secciones"]
    assert salida["secciones"]["experiencia"].startswith("Senior Developer")
    assert salida["texto_normalizado"].startswith("# Experiencia") or "Senior" in salida["texto_normalizado"]


def test_normaliza_texto_vacio():
    salida = normalizar_cv("")
    assert salida["secciones_presentes"] == []
    assert salida["texto_normalizado"] == ""