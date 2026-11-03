"""Regression: headings with emoji/accents and month-name ranges must not give false findings."""
from pathlib import Path

import pytest

import checker

FIXTURE = Path(__file__).parent / "fixtures" / "cv_master_estructura.md"


def test_real_structure_has_no_missing_sections_and_no_gaps():
    texto = FIXTURE.read_text(encoding="utf-8")
    assert checker.detectar_secciones_recuperables(checker.normalizar_cv(texto)) == []
    assert checker.detectar_gaps_temporales(texto) == []


@pytest.mark.parametrize("heading", [
    "💼 EXPERIENCIA LABORAL", "Experiencia profesional", "🛠️ HABILIDADES TÉCNICAS", "Skills",
    "🎓 FORMACIÓN", "Educación", "PROYECTOS", "🚀 PROYECTOS DESTACADOS",
])
def test_heading_variants_are_recognised(heading):
    cv = f"## {heading}\ncontenido\n"
    presentes = checker.detectar_secciones_recuperables(checker.normalizar_cv(cv))
    assert len(presentes) == 3  # only the one present is missing from the four


@pytest.mark.parametrize("texto", [
    "A Enero 2008 – Septiembre 2016\nB Junio 2017 – Mayo 2025",
    "A January 2008 - September 2016\nB June 2017 - Present",
    "A Mayo 2025 – Actualidad\nB Junio 2017 – Mayo 2025",
])
def test_month_name_ranges_do_not_create_fake_gaps(texto):
    assert checker.detectar_gaps_temporales(texto) == []


def test_a_real_gap_between_month_ranges_is_still_detected():
    assert len(checker.detectar_gaps_temporales("A Enero 2008 – Mayo 2010\nB Junio 2015 – Mayo 2025")) == 1


def test_cached_result_from_another_rules_version_is_not_reused(tmp_path):
    antiguo = tmp_path / "h1.json"
    antiguo.write_text('{"status": "warning", "hash_cv": "h1", "findings": [], "proposals": []}')
    nuevo = checker.persistir_analisis("h1", {"status": "ok", "findings": [], "proposals": []}, storage_dir=tmp_path)
    assert nuevo["status"] == "ok"
