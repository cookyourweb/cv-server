"""C12 - _ranking_fallback with an optional master keeps the old order without one."""
import real_jobs


def _of(i, descripcion, matches=0, modalidad="Remoto", salario=""):
    return {"id": i, "puesto": "Dev", "tags": [], "descripcion": descripcion,
            "_stack_matches": matches, "modalidad": modalidad, "salario": salario}


def test_S6_9_old_order_and_texts_without_master():
    ofertas = [_of("a", "x", 1), _of("b", "x", 3), _of("c", "x", 2)]
    r = real_jobs._ranking_fallback(ofertas, 2)
    assert [o["id"] for o in r] == ["b", "c"]
    assert r[0]["score"] == 75
    assert r[0]["motivo"] == "Encaja en 3 tecnologías de tu stack"


def test_master_puts_reachable_first_with_honest_reason():
    master = "Angular, RxJS, TypeScript"
    ofertas = [_of("mal", "Rust Scala Kotlin", 5), _of("bien", "Angular RxJS Rust", 1)]
    r = real_jobs._ranking_fallback(ofertas, 2, master_texto=master)
    assert [o["id"] for o in r] == ["bien", "mal"]
    assert r[0]["motivo"] == "Cubres 2 de 3; te falta: Rust"


def test_S6_10_tie_break_remote_then_salary_then_stack():
    master = "Angular"
    ofertas = [
        _of("presencial", "Angular", 9, modalidad="Presencial", salario="50k"),
        _of("remota_sin_sueldo", "Angular", 0),
        _of("remota_con_sueldo", "Angular", 0, salario="50k"),
    ]
    r = real_jobs._ranking_fallback(ofertas, 3, master_texto=master)
    assert [o["id"] for o in r] == ["remota_con_sueldo", "remota_sin_sueldo", "presencial"]


def test_offer_without_detectable_requirements_has_neutral_reason():
    r = real_jobs._ranking_fallback([_of("x", "Buenas personas")], 1, master_texto="Angular")
    assert "no se pueden" in r[0]["motivo"].lower()
