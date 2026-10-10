"""Sign-up with CV: users, emails, invitations, profile, encrypted CV masters,
extraction ledger, consents and runtime settings.

Revision ID: 0001_alta
Revises:
"""
from alembic import op

revision = "0001_alta"
down_revision = None
branch_labels = None
depends_on = None

TABLAS = ("ajustes", "consentimientos", "extracciones", "cv_master", "perfil",
          "invitaciones", "usuario_emails", "usuarios")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE usuarios (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            emisor text NOT NULL,
            sub text NOT NULL,
            nombre text,
            creado_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT usuarios_emisor_sub_unico UNIQUE (emisor, sub)
        )""")

    op.execute("""
        CREATE TABLE usuario_emails (
            email text PRIMARY KEY,
            usuario_id uuid NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
            principal boolean NOT NULL DEFAULT false,
            CONSTRAINT usuario_emails_en_minusculas CHECK (email = lower(email))
        )""")
    op.execute("CREATE INDEX usuario_emails_usuario_idx ON usuario_emails (usuario_id)")

    op.execute("""
        CREATE TABLE invitaciones (
            email text PRIMARY KEY,
            creada_en timestamptz NOT NULL DEFAULT now(),
            caduca_en timestamptz NOT NULL,
            usada_en timestamptz,
            usada_por uuid REFERENCES usuarios (id) ON DELETE SET NULL,
            CONSTRAINT invitaciones_en_minusculas CHECK (email = lower(email))
        )""")

    op.execute("""
        CREATE TABLE perfil (
            usuario_id uuid PRIMARY KEY REFERENCES usuarios (id) ON DELETE CASCADE,
            rol text,
            anios_experiencia smallint,
            stack text[] NOT NULL DEFAULT '{}',
            idiomas text[] NOT NULL DEFAULT '{}',
            ubicacion text,
            modalidad text[] NOT NULL DEFAULT '{}',
            salario_min integer,
            salario_moneda char(3),
            origen jsonb NOT NULL DEFAULT '{}'::jsonb,
            actualizado_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT perfil_anios_rango CHECK (anios_experiencia BETWEEN 0 AND 60),
            CONSTRAINT perfil_modalidad_valida
                CHECK (modalidad <@ ARRAY['remoto', 'hibrido', 'presencial']),
            CONSTRAINT perfil_salario_no_negativo CHECK (salario_min >= 0)
        )""")

    op.execute("""
        CREATE TABLE cv_master (
            usuario_id uuid NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
            idioma text NOT NULL,
            formato text NOT NULL,
            clave_version integer NOT NULL,
            nonce bytea NOT NULL,
            cifrado bytea NOT NULL,
            caracteres integer NOT NULL,
            subido_en timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (usuario_id, idioma),
            CONSTRAINT cv_master_idioma_valido CHECK (idioma IN ('es', 'en')),
            CONSTRAINT cv_master_formato_valido CHECK (formato IN ('pdf', 'docx')),
            CONSTRAINT cv_master_nonce_12_bytes CHECK (octet_length(nonce) = 12)
        )""")

    op.execute("""
        CREATE TABLE extracciones (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id uuid REFERENCES usuarios (id) ON DELETE SET NULL,
            modelo text NOT NULL,
            estado text NOT NULL,
            estimado_eur numeric(8, 4) NOT NULL,
            coste_eur numeric(8, 4),
            tokens_entrada integer,
            tokens_salida integer,
            creada_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT extracciones_estado_valido
                CHECK (estado IN ('reservada', 'completada', 'fallida'))
        )""")
    # One attempt per user. A failed provider call does not consume it, and rows
    # orphaned by an account deletion (usuario_id NULL) stay in the ledger unrestricted.
    op.execute("""
        CREATE UNIQUE INDEX extracciones_un_intento_por_usuaria
            ON extracciones (usuario_id)
            WHERE usuario_id IS NOT NULL AND estado <> 'fallida'""")
    op.execute("CREATE INDEX extracciones_creada_en_idx ON extracciones (creada_en)")

    op.execute("""
        CREATE TABLE consentimientos (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id uuid NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
            tipo text NOT NULL,
            version text NOT NULL,
            otorgado_en timestamptz NOT NULL DEFAULT now(),
            revocado_en timestamptz,
            CONSTRAINT consentimientos_tipo_valido CHECK (tipo IN ('almacenar_cv', 'enviar_cv_a_ia')),
            CONSTRAINT consentimientos_unico UNIQUE (usuario_id, tipo, version)
        )""")

    op.execute("""
        CREATE TABLE ajustes (
            clave text PRIMARY KEY,
            valor jsonb NOT NULL
        )""")
    op.execute("INSERT INTO ajustes (clave, valor) VALUES ('extraccion_activa', 'true'::jsonb)")


def downgrade() -> None:
    for tabla in TABLAS:
        op.execute(f"DROP TABLE IF EXISTS {tabla}")
