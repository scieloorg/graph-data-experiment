from __future__ import with_statement

import os, sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool

sys.path = sys.path + [os.path.abspath(".")]
from models import metadata

config = context.config
fileConfig(config.config_file_name) # Setup loggers


def run_migrations_offline():
    context.configure(
        url=os.environ["PGSQL_URL"],
        target_metadata=metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        url=os.environ["PGSQL_URL"],
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
