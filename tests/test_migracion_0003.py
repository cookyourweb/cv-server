"""Migration 0003_embeddings: pgvector extension and the per-offer embeddings table.

Same style as test_migracion_0002: schema tests run in a rolled-back transaction; the round trip
(one revision down and up) is destructive and gated by ALLOW_DESTRUCTIVE_DB_TESTS.
"""
import pytest
from alembic import command
from sqlalchemy import inspect, text

from embeddings import DIMENSIONES
from test_migracion_0001 import _alembic, _rechaza, _usuario, c, motor  # noqa: F401

pytestmark = pytest.mark.bd


def _vector(valor=0.1, n=DIMENSIONES):
    return "[" + ",".join([str(valor)] * n) + "]"


def _insertar(c, page="p1", uid=None, vector=None):  # noqa: F811
    c.execute(text("INSERT INTO embeddings_oferta (notion_page_id, usuario_id, modelo, huella, vector) "
                   "VALUES (:p, :u, 'm', 'h', CAST(:v AS vector))"),
              {"p": page, "u": uid, "v": vector or _vector()})


@pytest.mark.bd_destructiva
def test_downgrade_to_0002_and_back_is_clean(motor, url_de_pruebas):  # noqa: F811
    try:
        _alembic(command.downgrade, "0002_cuota", url_de_pruebas)
        nombres = set(inspect(motor).get_table_names())
        assert "embeddings_oferta" not in nombres and "intereses" in nombres
        _alembic(command.upgrade, "head", url_de_pruebas)
        assert "embeddings_oferta" in set(inspect(motor).get_table_names())
    finally:
        _alembic(command.upgrade, "head", url_de_pruebas)


def test_the_vector_extension_is_installed(c):  # noqa: F811
    assert c.execute(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")).scalar_one() == 1


def test_a_row_gets_a_timestamp_and_the_vector_has_the_configured_dimensions(c):  # noqa: F811
    _insertar(c, uid=_usuario(c))
    fila = c.execute(text("SELECT creado_en, vector_dims(vector) AS d FROM embeddings_oferta")).one()
    assert fila.creado_en is not None and fila.d == DIMENSIONES


def test_a_vector_of_the_wrong_length_is_rejected(c):  # noqa: F811
    uid = _usuario(c)
    _insertar(c, "ok", uid)  # the table exists and takes a right-sized vector
    with pytest.raises(Exception):
        with c.begin_nested():
            _insertar(c, "short", uid, vector=_vector(n=DIMENSIONES - 1))


def test_one_row_per_notion_page(c):  # noqa: F811
    uid = _usuario(c)
    _insertar(c, "p1", uid)
    with pytest.raises(Exception):
        with c.begin_nested():
            _insertar(c, "p1", uid)


def test_a_row_needs_an_owner_and_a_vector(c):  # noqa: F811
    _insertar(c, "ok", _usuario(c))  # the table exists
    _rechaza(c, "INSERT INTO embeddings_oferta (notion_page_id, modelo, huella, vector) "
                "VALUES ('x', 'm', 'h', CAST(:v AS vector))", v=_vector())
    _rechaza(c, "INSERT INTO embeddings_oferta (notion_page_id, usuario_id, modelo, huella) "
                "VALUES ('x', :u, 'm', 'h')", u=_usuario(c))


def test_deleting_the_user_deletes_her_embeddings(c):  # noqa: F811
    uid = _usuario(c)
    _insertar(c, uid=uid)
    c.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": uid})
    assert c.execute(text("SELECT count(*) FROM embeddings_oferta WHERE usuario_id = :u"), {"u": uid}).scalar_one() == 0


def test_the_foreign_key_cascades_and_the_indexes_exist(motor):  # noqa: F811
    fks = inspect(motor).get_foreign_keys("embeddings_oferta")
    assert [(fk["constrained_columns"], fk["options"].get("ondelete")) for fk in fks] == [(["usuario_id"], "CASCADE")]
    with motor.connect() as conexion:
        defs = " ".join(conexion.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'embeddings_oferta'")).scalars())
    assert "USING hnsw (vector vector_cosine_ops)" in defs and "(usuario_id)" in defs
