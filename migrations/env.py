from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from sentinelflow import models  # noqa: F401  (registers tables on Base.metadata)
from sentinelflow.core.config import get_settings
from sentinelflow.db.session import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A caller (including tests) can provide an explicit URL. Otherwise use the
# application configuration from DATABASE_URL/.env.
database_url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not configured. Copy .env.example to .env and set it."
    )
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# ``sentinelflow.models`` is imported above so Base.metadata is complete.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
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
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
