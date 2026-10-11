"""Owner-paid generation: spend ledger, monthly alarm marker and interest leads.

Revision ID: 0002_cuota
Revises: 0001_alta
"""
from alembic import op

revision = "0002_cuota"
down_revision = "0001_alta"
branch_labels = None
depends_on = None

TABLAS = ("intereses", "avisos_gasto", "gastos_generacion")


def upgrade() -> None:
    # One row per CV or cover letter generated on the owner's keys. The monthly cap sums
    # coalesce(coste_real, coste_estimado) over EVERY row; a user's quota sums `unidades` of
    # her rows that are not `fallida`. usuario_id is nulled (not deleted) with the account so
    # deleting an account cannot reset the global cap.
    op.execute("""
        CREATE TABLE gastos_generacion (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id uuid REFERENCES usuarios (id) ON DELETE SET NULL,
            tipo text NOT NULL,
            modelo text NOT NULL,
            unidades numeric(6, 2) NOT NULL,
            estado text NOT NULL,
            coste_estimado numeric(8, 4) NOT NULL,
            coste_real numeric(8, 4),
            tokens_entrada integer,
            tokens_salida integer,
            creado_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT gastos_generacion_tipo_valido CHECK (tipo IN ('cv', 'carta')),
            CONSTRAINT gastos_generacion_estado_valido
                CHECK (estado IN ('reservada', 'completada', 'fallida')),
            CONSTRAINT gastos_generacion_unidades_no_negativas CHECK (unidades >= 0),
            CONSTRAINT gastos_generacion_coste_no_negativo CHECK (coste_estimado >= 0)
        )""")
    op.execute("CREATE INDEX gastos_generacion_creado_en_idx ON gastos_generacion (creado_en)")
    op.execute("CREATE INDEX gastos_generacion_usuario_idx ON gastos_generacion (usuario_id, creado_en)")

    # Marker of the 70 % alarm: a row exists once the month's mail went out.
    op.execute("""
        CREATE TABLE avisos_gasto (
            mes date PRIMARY KEY,
            enviado_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT avisos_gasto_primer_dia CHECK (extract(day FROM mes) = 1)
        )""")

    # Leads of the "tell me about packs / access through my academy" button.
    op.execute("""
        CREATE TABLE intereses (
            usuario_id uuid NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
            tipo text NOT NULL,
            organizacion text,
            creado_en timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (usuario_id, tipo),
            CONSTRAINT intereses_tipo_valido CHECK (tipo IN ('paquetes', 'academia')),
            CONSTRAINT intereses_organizacion_corta CHECK (char_length(organizacion) <= 120)
        )""")


def downgrade() -> None:
    for tabla in TABLAS:
        op.execute(f"DROP TABLE IF EXISTS {tabla}")
