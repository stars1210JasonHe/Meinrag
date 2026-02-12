"""One-time migration: JSON files -> PostgreSQL.

Usage:
    uv run python scripts/migrate_json_to_pg.py

Reads existing data/metadata.json and data/users.json, inserts into PostgreSQL.
Requires DATABASE_URL to be configured in .env and the DB to have tables created
(run `alembic upgrade head` first).
"""
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.db.models import Base
from app.db.session import create_engine_and_session
from app.db.repositories import DocumentRepository, UserRepository


async def migrate():
    settings = Settings()
    engine, session_factory = create_engine_and_session(settings.database_url)

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user_repo = UserRepository(session)
        doc_repo = DocumentRepository(session)

        # --- Migrate users ---
        users_file = settings.users_file
        if users_file.exists():
            data = json.loads(users_file.read_text(encoding="utf-8"))
            users = data.get("users", {})
            count = 0
            for uid, user in users.items():
                if not await user_repo.exists(uid):
                    await user_repo.add(uid, user.get("display_name", uid.capitalize()))
                    count += 1
                    print(f"  + User: {uid}")
                else:
                    print(f"  = User already exists: {uid}")
            print(f"Users migrated: {count}")
        else:
            # Ensure default user exists
            if not await user_repo.exists(settings.default_user):
                await user_repo.add(settings.default_user, settings.default_user.capitalize())
            print("No users.json found, created default user only")

        # --- Migrate documents ---
        metadata_file = Path("data/metadata.json")
        if metadata_file.exists():
            data = json.loads(metadata_file.read_text(encoding="utf-8"))
            docs = data.get("documents", {})
            count = 0
            for doc_id, doc in docs.items():
                existing = await doc_repo.get(doc_id)
                if existing:
                    print(f"  = Document already exists: {doc_id} ({doc.get('filename', '?')})")
                    continue

                # Ensure the user exists
                user_id = doc.get("user_id", "admin")
                if not await user_repo.exists(user_id):
                    await user_repo.add(user_id, user_id.capitalize())
                    print(f"  + Auto-created user: {user_id}")

                # Handle old single-collection format
                collections = doc.get("collections")
                if not collections:
                    old_coll = doc.get("collection")
                    collections = [old_coll] if old_coll else ["other"]

                await doc_repo.add(
                    doc_id=doc_id,
                    filename=doc.get("filename", "unknown"),
                    file_type=doc.get("file_type", ".pdf"),
                    chunk_count=doc.get("chunk_count", 0),
                    collections=collections,
                    user_id=user_id,
                    file_hash=doc.get("file_hash"),
                )
                count += 1
                print(f"  + Document: {doc_id} ({doc.get('filename', '?')}) -> {collections}")

            print(f"Documents migrated: {count}")
        else:
            print("No metadata.json found, nothing to migrate")

        await session.commit()

    await engine.dispose()
    print("\nMigration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
