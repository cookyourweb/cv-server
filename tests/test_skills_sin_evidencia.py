from checker import detectar_skills_sin_evidencia


def test_skill_sin_evidencia():
    texto = """
# Experiencia
Desarrollador en ACME 2022-2024

# Skills
Python, Rust, Kubernetes
"""
    resultado = detectar_skills_sin_evidencia(texto)
    assert "Rust" in resultado or "Kubernetes" in resultado


def test_skill_con_evidencia():
    texto = """
# Experiencia
Usé Python y FastAPI en el backend durante 2023

# Skills
Python, FastAPI
"""
    resultado = detectar_skills_sin_evidencia(texto)
    assert "Python" not in resultado
    assert "FastAPI" not in resultado