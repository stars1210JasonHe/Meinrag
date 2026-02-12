import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import Base, UserModel
from app.db.repositories import DocumentRepository, UserRepository, ChatSessionRepository


TEST_DIR = Path("data/test_pytest")
TEST_CASES_DIR = Path("test cases")

# Real test PDFs provided by user
PDF_AI_SAFETY = TEST_CASES_DIR / "2512.20798v2.pdf"    # 17p, AI safety research
PDF_PATTERNS = TEST_CASES_DIR / "2602.10009v1.pdf"      # 20p, pattern discovery research
PDF_LAW = TEST_CASES_DIR / "80201000.pdf"               # 142p, German Basic Law


@pytest.fixture(scope="session", autouse=True)
def test_dir():
    """Create and clean up a temporary test directory."""
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    yield TEST_DIR
    shutil.rmtree(TEST_DIR, ignore_errors=True)


@pytest.fixture
def settings():
    """Return a Settings instance (reads from .env)."""
    return Settings()


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite database session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with session_factory() as session:
        # Create default admin user for FK constraints
        session.add(UserModel(user_id="admin", display_name="Admin"))
        await session.commit()
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def registry(db_session):
    """Fresh DocumentRepository for each test."""
    return DocumentRepository(db_session)


@pytest_asyncio.fixture
async def user_registry(db_session):
    """Fresh UserRepository for each test."""
    return UserRepository(db_session)


@pytest_asyncio.fixture
async def memory_manager(db_session):
    """Fresh ChatSessionRepository for each test (max=6, ttl=2s)."""
    return ChatSessionRepository(db_session, max_messages=6, session_ttl=2)


def has_api_key():
    """Check if OpenAI API key is available."""
    try:
        s = Settings()
        return bool(s.openai_api_key) and not s.openai_api_key.startswith("sk-YOUR")
    except Exception:
        return False


# Skip marker for tests requiring API key
online = pytest.mark.skipif(not has_api_key(), reason="No OPENAI_API_KEY configured")
