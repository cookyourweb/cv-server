"""Per-user job search: profile fields used by the daily search (spec 009).

Revision ID: 0005_perfil_busqueda
Revises: 0004_byok
"""
from alembic import op

revision = "0005_perfil_busqueda"
down_revision = "0004_byok"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE perfil
        ADD COLUMN IF NOT EXISTS regiones_remoto text[] NOT NULL DEFAULT '{}'
    """)
    op.execute("""
        ALTER TABLE perfil
        ADD COLUMN IF NOT EXISTS ciudades_hibrido text[] NOT NULL DEFAULT '{}'
    """)
    op.execute("""
        ALTER TABLE perfil
        ADD COLUMN IF NOT EXISTS tarifa_dia_min integer
    """)
    op.execute("""
        ALTER TABLE perfil
        ADD COLUMN IF NOT EXISTS evitar text
    """)
    op.execute("""
        ALTER TABLE perfil
        ADD CONSTRAINT perfil_tarifa_no_negativa
            CHECK (tarifa_dia_min IS NULL OR tarifa_dia_min >= 0)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE perfil DROP CONSTRAINT IF EXISTS perfil_tarifa_no_negativa")
    op.execute("ALTER TABLE perfil DROP COLUMN IF EXISTS evitar")
    op.execute("ALTER TABLE perfil DROP COLUMN IF EXISTS tarifa_dia_min")
    op.execute("ALTER TABLE perfil DROP COLUMN IF EXISTS ciudades_hibrido")
    op.execute("ALTER TABLE perfil DROP COLUMN IF EXISTS regiones_remoto")