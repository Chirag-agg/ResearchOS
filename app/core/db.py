from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlmodel import SQLModel
from app.core.config import settings
from app.models.session import ResearchSession

# SQLite requires check_same_thread=False when sharing connections across threads (default FastAPI behavior)
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """
    Initializes the database schema. Under an async engine, SQLAlchemy requires
    running metadata creation via the run_sync helper.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
