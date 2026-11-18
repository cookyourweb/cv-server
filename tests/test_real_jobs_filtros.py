"""Tests for T5 filters: spam + salary."""
import real_jobs


def test_filtrar_spam_descarta_bootcamp():
    ofertas = [
        {"puesto": "Dev", "tags": ["react"], "descripcion": "ok", "empresa": "A"},
        {"puesto": "Bootcamp React", "tags": [], "descripcion": "curso intensivo", "empresa": "B"},
    ]
    res = real_jobs.filtrar_spam(ofertas)
    assert len(res) == 1
    assert res[0]["empresa"] == "A"


def test_filtrar_spam_sin_terminos_conserva_todo():
    ofertas = [{"puesto": "Dev", "tags": [], "descripcion": "", "empresa": "A"}]
    assert len(real_jobs.filtrar_spam(ofertas, tags_spam=())) == 1


def test_salario_anual_k():
    assert real_jobs._salario_anual("40k") == 40000
    assert real_jobs._salario_anual("40k €/mes") == 480000


def test_salario_anual_numero():
    assert real_jobs._salario_anual("45000") == 45000


def test_salario_anual_none():
    assert real_jobs._salario_anual("") is None
    assert real_jobs._salario_anual("a negociar") is None


def test_filtrar_por_salario_descarta_bajos():
    ofertas = [
        {"salario": "30k"},
        {"salario": "60k"},
        {"salario": ""},
    ]
    res = real_jobs.filtrar_por_salario(ofertas, salario_min=50000)
    assert len(res) == 2  # 30k descartada, 60k y sin-salario conservadas


def test_filtrar_por_salario_sin_min_conserva_todo():
    ofertas = [{"salario": "10k"}, {"salario": "100k"}]
    assert len(real_jobs.filtrar_por_salario(ofertas, salario_min=0)) == 2