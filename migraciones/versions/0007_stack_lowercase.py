"""Normalize profile stack to lowercase.

Revision ID: 0007_stack_lowercase
Revises: 0006_normalizar_stack
"""
from alembic import op

revision = "0007_stack_lowercase"
down_revision = "0006_normalizar_stack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE perfil
        SET stack = (SELECT array_agg(DISTINCT lower(x))
                     FROM unnest(stack) x
                     WHERE x <> '')
        WHERE EXISTS (SELECT 1 FROM unnest(stack) s WHERE s <> lower(s))
    """)


def downgrade() -> None:
    pass