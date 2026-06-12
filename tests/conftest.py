import os
import pytest
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlmodel import SQLModel

# Force SQLite test database environment variable before any imports
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_research_os.db"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# Import app components after environment variable override
from app.main import app
from app.api.deps import get_db
from app.events.bus import EventBus

# Create test engine and sessionmaker
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

test_async_session_maker = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session", autouse=True)
async def init_test_db():
    """
    Initializes the database schema for the test session and tears it down afterwards.
    """
    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    # Drop tables
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    
    # Delete SQLite test db file if exists
    if os.path.exists("./test_research_os.db"):
        try:
            os.remove("./test_research_os.db")
        except PermissionError:
            pass


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a transactional database session for a test.
    """
    async with test_async_session_maker() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Provides an HTTPX AsyncClient configured to request endpoints against the FastAPI app
    with get_db dependency overridden to use the test database session.
    Also initializes a test EventBus in app.state for event-publishing endpoints.
    """
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Ensure EventBus is available in app.state for tests
    if not hasattr(app.state, "event_bus"):
        app.state.event_bus = EventBus()
    
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac
        
    app.dependency_overrides.clear()

