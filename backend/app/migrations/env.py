import asyncio
from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.core.config import settings
from app.db import Base


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def migrate_from_cli() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


# The application passes its own connection at startup; the alembic CLI does not.
supplied = context.config.attributes.get("connection")
if supplied is not None:
    migrate(supplied)
else:
    asyncio.run(migrate_from_cli())
