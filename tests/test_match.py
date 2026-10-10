"""C12 - honest rule-based match: pure, evidence-backed, never guessed."""
import ast
from pathlib import Path

import pytest

import match

RAIZ = Path(__file__).resolve().parent.parent
MASTER = "Frontend developer.\nAngular 8 años en banca.\nTrabajé con JavaScript y RxJS.\nGoogle Cloud para despliegues."


def _tipos(items):
    return {i["requisito"] for i in items}


def test_S6_1_angular_covered_with_evidence_rust_gap():
    e = match.evaluar("We need Angular and Rust", {}, MASTER)
    cubiertos = {c["requisito"]: c["evidencia"] for c in e.cubiertos}
    assert "Angular" in cubiertos and "Angular 8" in cubiertos["Angular"]
    assert "Rust" in _tipos(e.huecos)


def test_evidence_is_truncated():
    e = match.evaluar("Angular", {}, "Angular " + "x" * 400)
    assert len(e.cubiertos[0]["evidencia"]) <= 160


def test_S6_2_java_is_not_javascript():
    e = match.evaluar("Java required", {}, "Solo JavaScript")
    assert "Java" in _tipos(e.huecos) and not e.cubiertos


def test_S6_3_golang_is_not_google_cloud():
    e = match.evaluar("Golang required", {}, "Google Cloud Platform")
    assert "Golang" in _tipos(e.huecos)
    assert "GCP" not in _tipos(e.cubiertos)


def test_S6_4_soft_skill_is_not_evaluable():
    e = match.evaluar("Angular. Excelente comunicación y trabajo en equipo", {}, MASTER)
    assert e.no_evaluables
    assert not any("comunic" in r["requisito"].lower() for r in e.cubiertos + e.huecos)


def test_years_shortfall_is_eliminatory():
    e = match.evaluar("Angular, 10+ years of experience", {"anios_experiencia": 5}, MASTER)
    hueco = [h for h in e.huecos if h["eliminatorio"]]
    assert hueco and e.alcanzable is False


def test_years_met_is_covered():
    e = match.evaluar("Angular, 5 años de experiencia", {"anios_experiencia": 8}, MASTER)
    assert not [h for h in e.huecos if h["eliminatorio"]]
    assert e.alcanzable is True


def test_years_without_profile_is_not_evaluable():
    e = match.evaluar("Angular, 5 years of experience", {}, MASTER)
    assert any("5" in r for r in e.no_evaluables)
    assert not [h for h in e.huecos if h["eliminatorio"]]


def test_modalidad_mismatch_is_eliminatory():
    e = match.evaluar("Angular. On-site in Madrid", {"modalidad": ["remoto"]}, MASTER)
    assert [h for h in e.huecos if h["eliminatorio"]] and e.alcanzable is False


def test_language_mismatch_is_eliminatory():
    e = match.evaluar("Angular. Fluent German required", {"idiomas": ["es", "en"]}, MASTER)
    assert [h for h in e.huecos if h["eliminatorio"]]


def test_S6_5_only_small_gaps_is_reachable():
    # 4 covered, 1 gap: coverage 0.8, one tech gap, no eliminatory gap
    master = "Angular, RxJS, JavaScript, TypeScript"
    e = match.evaluar("Angular RxJS JavaScript TypeScript Rust", {}, master)
    assert e.cobertura == pytest.approx(0.8) and e.alcanzable is True


def test_not_reachable_with_low_coverage():
    e = match.evaluar("Angular Rust Scala Kotlin Swift", {}, "Angular")
    assert e.alcanzable is False


def test_not_reachable_with_more_than_two_tech_gaps():
    master = "Angular RxJS JavaScript TypeScript Vue.js React Redux Sass"
    e = match.evaluar("Angular RxJS JavaScript TypeScript Vue.js React Redux Sass Rust Scala Kotlin", {}, master)
    assert e.cobertura >= match.COBERTURA_MINIMA and e.alcanzable is False


def test_no_tech_requirements_is_not_reachable():
    e = match.evaluar("Buscamos persona con ganas", {}, MASTER)
    assert e.cobertura == 0.0 and e.alcanzable is False


def test_S6_8_motivation_does_not_cover_a_gap():
    perfil = {"motivacion": "Sé Kubernetes", "stack": ["Kubernetes"]}
    e = match.evaluar("Kubernetes", perfil, MASTER)
    assert "Kubernetes" in _tipos(e.huecos) and not e.cubiertos


@pytest.mark.parametrize("texto,master", [("", ""), (None, None), ("Angular", None), (None, "Angular")])
def test_empty_inputs_do_not_raise(texto, master):
    e = match.evaluar(texto, None, master)
    assert e.cubiertos == [] or isinstance(e.cubiertos, list)
    assert isinstance(e.alcanzable, bool)


def test_as_dict_has_the_api_shape():
    d = match.evaluar("Angular Rust", {}, MASTER).a_dict()
    assert set(d) == {"cubiertos", "huecos", "no_evaluables", "alcanzable", "cobertura"}


def test_S6_6_purity_no_io_network_llm_or_clock():
    arbol = ast.parse((RAIZ / "match.py").read_text(encoding="utf-8"))
    importados = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            importados |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            importados.add((n.module or "").split(".")[0])
    permitidos = {"__future__", "re", "dataclasses", "typing", "guardrails"}
    assert importados <= permitidos, importados - permitidos
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not llamadas & {"open", "print", "input", "exec", "eval"}


def test_REQ_6_3_match_never_reaches_the_generators():
    """Only real_jobs may import match; the CV/letter generators must not."""
    importadores = set()
    for f in RAIZ.glob("*.py"):
        if f.name == "match.py":
            continue
        arbol = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            nombres = []
            if isinstance(n, ast.Import):
                nombres = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                nombres = [(n.module or "").split(".")[0]]
            if "match" in nombres:
                importadores.add(f.name)
    assert importadores <= {"real_jobs.py"}, importadores


def test_redos_whitespace_runs_in_the_offer_stay_fast():
    import time
    casos = [
        "5" + " " * 50_000 + "years",
        "5 years" + " " * 50_000 + "x",
        "fluent" + " " * 50_000 + "english",
        "english" + " " * 50_000 + "(" + " " * 50_000 + "x",
    ]
    for oferta in casos:
        inicio = time.perf_counter()
        match.evaluar(oferta, {"anios_experiencia": 3}, MASTER)
        assert time.perf_counter() - inicio < 0.5


def test_oversized_inputs_are_capped_before_matching():
    # A requirement beyond the cap is ignored; one inside it is still found.
    oferta = "Angular " + "x " * 30_000 + "Rust"
    e = match.evaluar(oferta, {}, MASTER)
    assert "Angular" in _tipos(e.cubiertos)
    assert "Rust" not in _tipos(e.huecos)


def test_match_uses_public_guardrails_helpers():
    import guardrails
    assert guardrails.tecnologias_en("Angular") == {"Angular"}
    assert guardrails.plano("Ñandú") == guardrails._plano("Ñandú")
    assert "guardrails._" not in (RAIZ / "match.py").read_text(encoding="utf-8")
