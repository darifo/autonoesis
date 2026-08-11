"""Alembic environment for the authoritative PostgreSQL schema."""

import os
import re
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from autonoesis_adapters.persistence import metadata
from sqlalchemy import engine_from_config, pool

config = context.config
if database_url := os.getenv("AUTONOESIS_MIGRATION_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if migration_role := os.getenv("AUTONOESIS_MIGRATION_ROLE"):
            if re.fullmatch(r"[a-z_][a-z0-9_]*", migration_role) is None:
                raise ValueError("AUTONOESIS_MIGRATION_ROLE is not a safe PostgreSQL identifier")
            connection.execute(sa.text(f'SET ROLE "{migration_role}"'))
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
