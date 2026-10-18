"""encaje_semantico: pure semantic-fit scoring and hard rules (flag, never discard)."""
import ast
from pathlib import Path

import pytest

import encaje_semantico as es

RAIZ = Path(__file__).resolve().parent.parent


# ─── Cosine / score / duplicates ────────────────────────────────────────────

def test_coseno_mismo_vector_es_uno():
    assert es.coseno([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_coseno_perpendiculares_es_cero():
    assert es.coseno([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_coseno_opuestos_es_menos_uno():
    assert es.coseno([1.0, 2.0], [-1.0, -2.0]) == pytest.approx(-1.0)


def test_coseno_no_depende_de_la_longitud():
    assert es.coseno([1.0, 1.0], [10.0, 10.0]) == pytest.approx(1.0)


def test_coseno_con_vector_nulo_es_cero_no_division_por_cero():
    assert es.coseno([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_puntuar_resta_lo_que_evito():
    s = es.puntuar([1.0, 0.0], [0.0, 1.0], [0.2, 1.0])
    assert s == pytest.approx(es.coseno([1.0, 0.0], [0.2, 1.0]) - es.coseno([0.0, 1.0], [0.2, 1.0]))
    assert s < 0


def test_puntuar_sin_antiperfil_no_resta_nada():
    assert es.puntuar([1.0, 0.0], None, [1.0, 0.0]) == pytest.approx(1.0)


def test_es_duplicada_solo_por_encima_del_umbral():
    assert es.es_duplicada(0.96) is True
    assert es.es_duplicada(0.95) is False
    assert es.es_duplicada(0.90, umbral=0.8) is True


# ─── Salary parsing (real examples from the data) ───────────────────────────

@pytest.mark.parametrize("texto, esperado", [
    ("111.000-143.000 EUR", 111000),
    ("60.000 € - 90.000 € brutos/año", 60000),
    ("62400-312000 EUR (equiv. $30-$150/hr)", 62400),
    ("120000-170000 EUR", 120000),
    ("28.000-32.000 € brutos/año", 28000),
    ("35k (tarifa orientativa)", 35000),
    ("90000-140000", 90000),
    ("$120k 150k", 120000),
    ("62,5k", 62500),
    ("45.000", 45000),
])
def test_parsear_salario_min_formatos_reales(texto, esperado):
    assert es.parsear_salario_min(texto) == esperado


@pytest.mark.parametrize("texto", [
    "s/i",
    "",
    None,
    "   ",
    "Vero pidió mín. 60k (España) / 90-120k (empresa extranjera)",  # prose + two figures
    "90-120k",            # "90" has no k: could be 90 or 90k, so it is not guessed
    "45.5",               # decimal without k: ambiguous
    "3000 EUR al mes",    # monthly, not annual
    "50 EUR/hora",        # hourly
    "competitivo",
    "800",                # below 1000: not an annual figure
])
def test_parsear_salario_min_ambiguo_es_none(texto):
    assert es.parsear_salario_min(texto) is None


# ─── Hard rules ─────────────────────────────────────────────────────────────

PREFS = {"salario_min": 60000, "ciudad": "Madrid"}


def test_salario_bajo_cuando_el_minimo_parseado_esta_por_debajo():
    assert es.reglas_duras({"salario": "28.000-32.000 € brutos/año", "modalidad": "Remoto"}, PREFS) == ["salario_bajo"]


def test_salario_igual_o_superior_no_es_motivo():
    assert es.reglas_duras({"salario": "60000-70000"}, PREFS) == []


def test_salario_desconocido_no_es_motivo():
    for s in (None, "", "s/i", "competitivo"):
        assert es.reglas_duras({"salario": s}, PREFS) == []


def test_sin_salario_minimo_en_el_perfil_no_hay_motivo():
    for pref in ({"salario_min": 0}, {"salario_min": None}, {}):
        assert es.reglas_duras({"salario": "10000"}, pref) == []


@pytest.mark.parametrize("modalidad", ["Presencial", "Hibrido", "Híbrido"])
def test_ubicacion_fuera_de_la_ciudad_en_presencial_o_hibrido(modalidad):
    o = {"modalidad": modalidad, "ubicacion": "Barcelona"}
    assert es.reglas_duras(o, PREFS) == ["ubicacion"]


def test_ubicacion_en_la_ciudad_ignora_mayusculas_y_acentos():
    o = {"modalidad": "Presencial", "ubicacion": "MADRID, España"}
    assert es.reglas_duras(o, {"ciudad": "Madrid"}) == []
    o = {"modalidad": "Presencial", "ubicacion": "Málaga"}
    assert es.reglas_duras(o, {"ciudad": "malaga"}) == []


def test_area_de_madrid_cuenta_como_madrid():
    o = {"modalidad": "Hibrido", "ubicacion": "Pozuelo de Alarcón"}
    assert es.reglas_duras(o, PREFS) == []


def test_remoto_nunca_es_motivo_de_ubicacion():
    assert es.reglas_duras({"modalidad": "Remoto", "ubicacion": "Berlin"}, PREFS) == []


def test_ubicacion_o_modalidad_desconocidas_no_son_motivo():
    assert es.reglas_duras({"modalidad": "Presencial", "ubicacion": None}, PREFS) == []
    assert es.reglas_duras({"modalidad": "Presencial", "ubicacion": "Sin confirmar"}, PREFS) == []
    assert es.reglas_duras({"modalidad": "Sin confirmar", "ubicacion": "Berlin"}, PREFS) == []
    assert es.reglas_duras({"modalidad": None, "ubicacion": "Berlin"}, PREFS) == []


def test_sin_ciudad_en_el_perfil_no_hay_motivo():
    assert es.reglas_duras({"modalidad": "Presencial", "ubicacion": "Berlin"}, {"ciudad": ""}) == []


def test_pueden_darse_los_dos_motivos():
    o = {"salario": "30000", "modalidad": "Presencial", "ubicacion": "Berlin"}
    assert es.reglas_duras(o, PREFS) == ["salario_bajo", "ubicacion"]


# ─── Texts ──────────────────────────────────────────────────────────────────

def test_texto_de_perfil_junta_perfil_rol_y_stack():
    t = es.texto_de_perfil({"perfil": "Frontend senior", "rol": "Full stack", "stack": ["React", "Python"]})
    assert "Frontend senior" in t and "Full stack" in t and "React, Python" in t


def test_texto_de_perfil_omite_lo_vacio():
    assert es.texto_de_perfil({"perfil": "Solo perfil", "rol": "", "stack": []}) == "Solo perfil"
    assert es.texto_de_perfil({}) == ""


def test_texto_de_oferta_formato_y_truncado():
    assert es.texto_de_oferta({"puesto": "Dev", "empresa": "Acme", "descripcion": "React"}) == "Dev en Acme. React"
    largo = es.texto_de_oferta({"puesto": "Dev", "empresa": "Acme", "descripcion": "x" * 5000})
    assert len(largo) == 2000


def test_texto_de_oferta_con_campos_ausentes():
    assert es.texto_de_oferta({"puesto": "Dev"}).startswith("Dev en")


# ─── Purity ─────────────────────────────────────────────────────────────────

def test_pureza_sin_io_red_llm_ni_reloj():
    arbol = ast.parse((RAIZ / "encaje_semantico.py").read_text(encoding="utf-8"))
    importados = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            importados |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            importados.add((n.module or "").split(".")[0])
    assert importados <= {"__future__", "math", "re", "unicodedata", "typing"}, importados
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not llamadas & {"open", "print", "input", "exec", "eval"}
