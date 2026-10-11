import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.access.api import load_local_env  # noqa: E402

load_local_env()
from app.access import models  # noqa: E402,F401
from app.access.db import Base  # noqa: E402

url = os.environ.get("ACCESS_DATABASE_URL")
if not url:
    raise RuntimeError("ACCESS_DATABASE_URL is not set")


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, version_table="access_alembic_version")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
