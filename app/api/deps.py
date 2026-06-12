from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session_maker
from app.core.config import settings
from fastapi import Depends
from app.services.llm import LLMService
from app.services.search import SearchService
from app.repositories.session import SessionRepository
from app.repositories.query import QueryRepository
from app.repositories.search_result import SearchResultRepository


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


def get_search_service() -> SearchService:
    """
    Dependency injector for the SearchService, initialized with SearXNG URL.
    """
    return SearchService(api_url=settings.SEARXNG_URL)


def get_query_repository(session: AsyncSession = Depends(get_db)) -> QueryRepository:
    """
    Dependency injector that initializes and returns a QueryRepository instance.
    """
    return QueryRepository(session)


def get_search_result_repository(session: AsyncSession = Depends(get_db)) -> SearchResultRepository:
    """
    Dependency injector that initializes and returns a SearchResultRepository instance.
    """
    return SearchResultRepository(session)
