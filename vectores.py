"""Offer embeddings stored in pgvector (table `embeddings_oferta`, migration 0003).

Vectors travel as the pgvector text literal ('[0.1,0.2,...]') cast with `::vector`, so no extra
driver package is needed. The connection (and its transaction) belongs to the caller: nothing
here commits. Every lookup is scoped by `usuario_id`, so one user's offers never match another's.
"""
import hashlib

from sqlalchemy import text

from embeddings import DIMENSIONES


def huella(texto: str) -> str:
    """sha256 of the embedded text: an unchanged offer is not embedded twice."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _validar(vector: list[float]) -> str:
    if len(vector) != DIMENSIONES:
        raise ValueError(f"the vector must have {DIMENSIONES} dimensions, got {len(vector)}")
    return _literal(vector)


def guardar(conexion, notion_page_id: str, usuario_id, modelo: str, huella: str, vector: list[float]) -> None:
    """Insert or overwrite the embedding of one offer page."""
    literal = _validar(vector)
    conexion.execute(text(
        "INSERT INTO embeddings_oferta (notion_page_id, usuario_id, modelo, huella, vector) "
        "VALUES (:p, :u, :m, :h, CAST(:v AS vector)) "
        "ON CONFLICT (notion_page_id) DO UPDATE SET usuario_id = EXCLUDED.usuario_id, "
        "modelo = EXCLUDED.modelo, huella = EXCLUDED.huella, vector = EXCLUDED.vector, creado_en = now()"),
        {"p": notion_page_id, "u": usuario_id, "m": modelo, "h": huella, "v": literal})


def huella_guardada(conexion, notion_page_id: str) -> str | None:
    return conexion.execute(text("SELECT huella FROM embeddings_oferta WHERE notion_page_id = :p"),
                            {"p": notion_page_id}).scalar_one_or_none()


def mas_parecida(conexion, usuario_id, vector: list[float], excluir_page_id: str) -> tuple[str, float] | None:
    """The user's stored offer closest to `vector` as (notion_page_id, cosine similarity)."""
    literal = _validar(vector)
    fila = conexion.execute(text(
        "SELECT notion_page_id, 1 - (vector <=> CAST(:v AS vector)) AS similitud FROM embeddings_oferta "
        "WHERE usuario_id = :u AND notion_page_id <> :x "
        "ORDER BY vector <=> CAST(:v AS vector) LIMIT 1"),
        {"v": literal, "u": usuario_id, "x": excluir_page_id}).first()
    return None if fila is None else (fila.notion_page_id, float(fila.similitud))
