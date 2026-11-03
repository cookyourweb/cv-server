from checker import detectar_secciones_recuperables, normalizar_cv


def test_falta_skills_y_educacion():
    texto = """
# Experiencia
Desarrollador 2022-2024

# Proyectos
Panel CRM
"""
    normalizado = normalizar_cv(texto)
    faltantes = detectar_secciones_recuperables(normalizado)

    assert "habilidades" in faltantes
    assert "educacion" in faltantes


def test_no_faltan_secciones():
    texto = """
# Experiencia
Dev 2022-2024

# Skills
Python

# Educacion
Grado

# Proyectos
App
"""
    normalizado = normalizar_cv(texto)
    assert detectar_secciones_recuperables(normalizado) == []