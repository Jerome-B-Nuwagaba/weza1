import os

from alembic import context
from sqlalchemy import create_engine, text

from weza.config import get_settings
from weza.models import metadata
from weza.platform.db import DOMAIN_SCHEMAS


def _url() -> str:
    return os.environ.get("WEZA_TEST_DATABASE_URL") or get_settings().sqlalchemy_url


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        for schema in DOMAIN_SCHEMAS:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.commit()
        context.configure(connection=connection, target_metadata=metadata, include_schemas=True,
                          version_table_schema="platform", compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
