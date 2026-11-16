"""Normalize profile stack: split space/comma-joined values into separate tags.

Revision ID: 0006_normalizar_stack
Revises: 0005_perfil_busqueda
"""
from alembic import op

revision = "0006_normalizar_stack"
down_revision = "0005_perfil_busqueda"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE perfil
        SET stack = COALESCE(
            (SELECT array_agg(DISTINCT lower(x))
             FROM unnest(regexp_split_to_array(array_to_string(stack, ' '), '[,\\s]+')) x
             WHERE x <> ''),
            '{}'::text[])
        WHERE EXISTS (
            SELECT 1 FROM unnest(stack) s WHERE s ~ '[,\\s]'
        )
    """)


def downgrade() -> None:
    # No-op: the previous (joined) form is not recoverable.
    pass