"""Alembic environment.

The connection string comes from DATABASE_URL in the environment, never from
alembic.ini, so no credential can end up in version control. Migrations are written
by hand with explicit SQL (no ORM models, so there is no autogenerate metadata).
"""
import os
from logging.config import fileConfig

from alembic import context

from base_de_datos import ErrorDeBaseDeDatos, crear_motor

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _motor():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ErrorDeBaseDeDatos("DATABASE_URL is not set")
    return crear_motor(url)


def run_migrations_online() -> None:
    motor = _motor()
    try:
        with motor.connect() as conexion:
            context.configure(connection=conexion, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        motor.dispose()


run_migrations_online()
