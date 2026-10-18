"""Semantic fit: pgvector extension and one embedding per scored Notion offer.

Revision ID: 0003_embeddings
Revises: 0002_cuota
"""
from alembic import op

revision = "0003_embeddings"
down_revision = "0002_cuota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # One vector per offer page. `huella` is the sha256 of the embedded text, so an unchanged
    # offer is never embedded twice. 768 dimensions (embeddings.DIMENSIONES): HNSW indexes
    # accept at most 2000. The vectors are derived from offer text, but they are owned by the
    # user whose board they belong to, so they die with her account.
    op.execute("""
        CREATE TABLE embeddings_oferta (
            notion_page_id text PRIMARY KEY,
            usuario_id uuid NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
            modelo text NOT NULL,
            huella text NOT NULL,
            vector vector(768) NOT NULL,
            creado_en timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX embeddings_oferta_usuario_idx ON embeddings_oferta (usuario_id)")
    op.execute("CREATE INDEX embeddings_oferta_vector_idx ON embeddings_oferta "
               "USING hnsw (vector vector_cosine_ops)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embeddings_oferta")
    # The extension stays: it is harmless, dropping it needs more privileges than the table,
    # and 0003 re-creates it with IF NOT EXISTS, so base -> head round trips still work.
