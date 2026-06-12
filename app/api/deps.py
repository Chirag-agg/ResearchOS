from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session_maker
from app.core.config import settings
from fastapi import Depends
from app.services.llm import LLMService
from app.repositories.session import SessionRepository


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency generator that yields an active async database session.
    Automatically closes the session after request completion.
    """
    async with async_session_maker() as session:
        yield session


def get_llm_service() -> LLMService:
    """
    Dependency injector for the LLMService, initialized with core configuration.
    """
    return LLMService(
        api_url=settings.OLLAMA_API_URL,
        model_name=settings.LLM_MODEL
    )


def get_session_repository(session: AsyncSession = Depends(get_db)) -> SessionRepository:
    """
    Dependency injector that initializes and returns a SessionRepository instance.
    """
    return SessionRepository(session)
