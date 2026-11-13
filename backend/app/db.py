import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from .core.config import settings

logger = logging.getLogger(__name__)
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
BASELINE_REVISION = "0001"


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def run_migrations(connection: Connection) -> None:
    """Bring the schema to the latest revision without touching existing rows.

    Databases created before migrations existed (by ``create_all``) already hold
    the baseline tables but no version marker, so they are stamped, not rebuilt.
    """
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.attributes["connection"] = connection
    if connection.dialect.name == "postgresql":
        # Serialises concurrent startups (several replicas) for this transaction.
        connection.execute(text("SELECT pg_advisory_xact_lock(4711001)"))
    tables = set(inspect(connection).get_table_names())
    if "alembic_version" not in tables and "inspections" in tables:
        logger.info("Existing pre-migration schema found; stamping baseline %s", BASELINE_REVISION)
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(run_migrations)


async def database_is_reachable() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database health check failed")
        return False
