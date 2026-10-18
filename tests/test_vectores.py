"""vectores.py: embeddings of offers stored in pgvector.

The pure tests need no database. The bd ones use the test database inside a rolled-back
transaction, so they leave no rows behind.
"""
import pytest

import vectores
from embeddings import DIMENSIONES
from test_migracion_0001 import _usuario, c, motor  # noqa: F401


def _v(*cabeza):
    """A DIMENSIONES-long vector starting with `cabeza`, padded with zeros."""
    return list(cabeza) + [0.0] * (DIMENSIONES - len(cabeza))


# --- pure --------------------------------------------------------------------------------

def test_the_fingerprint_is_a_stable_sha256_of_the_text():
    assert vectores.huella("hola") == "b221d9dbb083a7f33428d7c2a3c3198ae925614d70210e28716ccaa7cd4ddb79"
    assert vectores.huella("hola") == vectores.huella("hola")
    assert vectores.huella("hola") != vectores.huella("hola ")


@pytest.mark.parametrize("n", [0, 1, DIMENSIONES - 1, DIMENSIONES + 1])
def test_a_vector_of_the_wrong_length_is_rejected_before_any_sql(n):
    with pytest.raises(ValueError, match=str(DIMENSIONES)):
        vectores.guardar(None, "p", "u", "m", "h", [0.1] * n)
    with pytest.raises(ValueError, match=str(DIMENSIONES)):
        vectores.mas_parecida(None, "u", [0.1] * n, "p")


def test_the_literal_is_the_pgvector_text_format():
    assert vectores._literal([0.5, -1, 2.25]) == "[0.5,-1.0,2.25]"


# --- database ----------------------------------------------------------------------------


@pytest.mark.bd
def test_nothing_stored_means_no_fingerprint(c):  # noqa: F811
    assert vectores.huella_guardada(c, "no-existe") is None


@pytest.mark.bd
def test_saving_twice_overwrites_the_row(c):  # noqa: F811
    uid = _usuario(c)
    vectores.guardar(c, "p1", uid, "m1", "h1", _v(1.0))
    vectores.guardar(c, "p1", uid, "m2", "h2", _v(0.0, 1.0))
    assert vectores.huella_guardada(c, "p1") == "h2"
    assert vectores.mas_parecida(c, uid, _v(0.0, 1.0), "otra") == ("p1", pytest.approx(1.0))
    from sqlalchemy import text
    fila = c.execute(text("SELECT count(*) AS n, max(modelo) AS m FROM embeddings_oferta "
                          "WHERE notion_page_id = 'p1'")).one()
    assert (fila.n, fila.m) == (1, "m2")


@pytest.mark.bd
def test_the_identical_vector_has_similarity_one(c):  # noqa: F811
    uid = _usuario(c)
    vectores.guardar(c, "p1", uid, "m", "h", _v(0.3, 0.4, 0.5))
    pagina, similitud = vectores.mas_parecida(c, uid, _v(0.3, 0.4, 0.5), "otra")
    assert pagina == "p1" and similitud == pytest.approx(1.0, abs=1e-6)


@pytest.mark.bd
def test_the_nearest_neighbour_is_the_closest_one(c):  # noqa: F811
    uid = _usuario(c)
    vectores.guardar(c, "lejos", uid, "m", "h", _v(0.0, 1.0))
    vectores.guardar(c, "cerca", uid, "m", "h", _v(1.0, 0.1))
    pagina, similitud = vectores.mas_parecida(c, uid, _v(1.0), "otra")
    assert pagina == "cerca" and 0.9 < similitud < 1.0


@pytest.mark.bd
def test_another_users_identical_vector_is_never_returned(c):  # noqa: F811
    yo, otra = _usuario(c), _usuario(c)
    vectores.guardar(c, "de-otra", otra, "m", "h", _v(1.0))
    vectores.guardar(c, "mia", yo, "m", "h", _v(0.0, 1.0))
    pagina, similitud = vectores.mas_parecida(c, yo, _v(1.0), "x")
    assert pagina == "mia" and similitud < 0.5


@pytest.mark.bd
def test_the_excluded_page_is_skipped_and_none_is_returned_when_nothing_else_exists(c):  # noqa: F811
    uid = _usuario(c)
    vectores.guardar(c, "p1", uid, "m", "h", _v(1.0))
    assert vectores.mas_parecida(c, uid, _v(1.0), "p1") is None
    vectores.guardar(c, "p2", uid, "m", "h", _v(0.0, 1.0))
    assert vectores.mas_parecida(c, uid, _v(1.0), "p1")[0] == "p2"
