"""BYOK: clave de IA propia y trial de 3 generaciones por usuaria.

Revision ID: 0004_byok
Revises: 0003_embeddings
"""
from alembic import op

revision = "0004_byok"
down_revision = "0003_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE usuarios
        ADD COLUMN IF NOT EXISTS trial_generaciones smallint NOT NULL DEFAULT 3
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS claves_api (
            usuario_id uuid NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
            proveedor text NOT NULL,
            clave_version integer NOT NULL,
            nonce bytea NOT NULL,
            cifrado bytea NOT NULL,
            actualizado_en timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (usuario_id, proveedor),
            CONSTRAINT claves_api_proveedor_valido CHECK (proveedor IN ('anthropic', 'groq'))
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS claves_api_usuario_idx ON claves_api (usuario_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS claves_api")
    op.execute("ALTER TABLE usuarios DROP COLUMN IF EXISTS trial_generaciones")