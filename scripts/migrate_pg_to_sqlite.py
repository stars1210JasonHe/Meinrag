"""One-shot script: copy PostgreSQL data into a SQLite database.

Usage (requires both asyncpg and aiosqlite):
    uv run python scripts/migrate_pg_to_sqlite.py \
        --pg "postgresql+asyncpg://postgres:postgres@localhost:5432/meinrag" \
        --sqlite "sqlite+aiosqlite:///data/meinrag.db"
"""
import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base

TABLES = ["users", "documents", "document_collections", "chat_sessions", "chat_messages"]


async def migrate(pg_url: str, sqlite_url: str) -> None:
    pg_engine = create_async_engine(pg_url)
    sq_engine = create_async_engine(
        sqlite_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    # Create tables in SQLite
    async with sq_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for table_name in TABLES:
        async with pg_engine.connect() as pg_conn:
            result = await pg_conn.execute(text(f"SELECT * FROM {table_name}"))
            rows = result.mappings().all()

        if not rows:
            print(f"  {table_name}: 0 rows (skipped)")
            continue

        table = Base.metadata.tables[table_name]
        async with sq_engine.begin() as sq_conn:
            for row in rows:
                await sq_conn.execute(table.insert().values(**dict(row)))

        print(f"  {table_name}: {len(rows)} rows migrated")

    await pg_engine.dispose()
    await sq_engine.dispose()
    print("Done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate MEINRAG data from PostgreSQL to SQLite")
    parser.add_argument("--pg", required=True, help="PostgreSQL URL")
    parser.add_argument("--sqlite", default="sqlite+aiosqlite:///data/meinrag.db", help="SQLite URL")
    args = parser.parse_args()
    asyncio.run(migrate(args.pg, args.sqlite))
