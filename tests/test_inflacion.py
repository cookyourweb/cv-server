"""C11 - inflation guardrail: ownership/superlative claims the master does not make."""
import pytest

import guardrails as g


def test_S7_1_unico_flagged():
    assert g.detectar_inflacion("Fui el único responsable del front.", "Trabajé en el front.")


def test_S7_2_master_has_it_not_flagged():
    assert g.detectar_inflacion("Fui el único responsable.", "Era la única desarrolladora front.") == []


def test_S7_3_nothing_to_flag():
    assert g.detectar_inflacion("Desarrollé componentes en Angular.", "Angular 8 años.") == []


@pytest.mark.parametrize("texto,master", [("", ""), (None, None), ("algo", None), (None, "algo"), ("", "algo")])
def test_S7_4_empty_or_none_returns_list(texto, master):
    assert g.detectar_inflacion(texto, master) == []


def test_S7_5_uppercase_without_accent():
    assert g.detectar_inflacion("RESPONSABLE UNICO del proyecto", "Responsable del proyecto")


def test_S7_6_lidere_counts_as_liderado_variant():
    # Design overrides spec S7.6: "lideré" is a variant of the liderado concept.
    assert g.detectar_inflacion("Equipo liderado por mí", "Lideré un equipo de tres") == []
    assert g.detectar_inflacion("Equipo liderado por mí", "Formé parte de un equipo")


def test_S7_7_english_led_flagged():
    assert g.detectar_inflacion("I led the whole migration", "I worked on the migration")


def test_word_boundaries():
    # "ledger" must not trigger "led"; "unicode" must not trigger "unico"
    assert g.detectar_inflacion("Built a ledger with unicode support", "Built things") == []


@pytest.mark.parametrize("texto", [
    "We only use Angular", "Full-stack developer", "Gave a reference to the team",
    "Worked full time", "Provided a reference letter",
])
def test_common_words_do_not_false_positive(texto):
    assert g.detectar_inflacion(texto, "Built things") == []


@pytest.mark.parametrize("texto", [
    "I was the only developer", "Full ownership of the product", "End-to-end delivery",
    "The go-to person for Angular", "Una solución completa", "Fui el referente técnico",
])
def test_phrases_that_are_claims_are_flagged(texto):
    assert g.detectar_inflacion(texto, "Built things")


def test_one_finding_per_concept():
    assert len(g.detectar_inflacion("único, unique y sole", "nada")) == 1


def test_S7_8_registered_for_cv_and_carta():
    nombres_cv = {x.nombre for x in g.guardrails_para(g.CV)}
    nombres_carta = {x.nombre for x in g.guardrails_para(g.CARTA)}
    assert "inflacion" in nombres_cv and "inflacion" in nombres_carta
    avisos = g.revisar("Fui el único responsable", "Trabajé en el front", g.CV)
    assert any(a.regla == "inflacion" for a in avisos)
