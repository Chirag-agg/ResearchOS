from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session_maker
from app.core.config import settings
from fastapi import Depends, Request
from app.services.llm import LLMService
from app.services.search import SearchService
from app.services.scraper import ScraperService
from app.repositories.session import SessionRepository
from app.repositories.query import QueryRepository
from app.repositories.search_result import SearchResultRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.event import EventRepository
from app.events.bus import EventBus
from app.services.claim_extractor import ClaimExtractor
from app.repositories.claim import ClaimRepository
from app.repositories.validation import ValidationRepository
from app.services.validator import ClaimValidator
from app.services.coordinator import ResearchCoordinator
from app.repositories.page_knowledge import PageKnowledgeRepository
from app.services.page_understanding import PageUnderstandingService
from app.repositories.knowledge import KnowledgeRepository
from app.services.knowledge_builder import KnowledgeBuilderService
from app.repositories.gap import GapRepository
from app.services.gap_discovery import GapDiscoveryService
from app.repositories.followup import FollowupQueryRepository
from app.services.research_planner import ResearchPlannerV2
from app.services.iterative_coordinator import IterativeResearchCoordinator
from app.repositories.strategy import StrategyRepository
from app.services.strategy_learning import StrategyLearningEngine
from app.services.telemetry import TelemetryService
from app.core.db import async_session_maker as _telemetry_session_maker


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


def get_scraper_service() -> ScraperService:
    """
    Dependency injector for the ScraperService, initialized with Playwright
    timeout and HTML storage directory from settings.
    """
    return ScraperService(
        timeout_ms=settings.PLAYWRIGHT_TIMEOUT_MS,
        html_storage_dir=settings.HTML_STORAGE_DIR,
    )


def get_fetched_page_repository(session: AsyncSession = Depends(get_db)) -> FetchedPageRepository:
    """
    Dependency injector that initializes and returns a FetchedPageRepository instance.
    """
    return FetchedPageRepository(session)


def get_event_bus(request: Request) -> EventBus:
    """
    Dependency injector that returns the application-wide EventBus singleton
    stored in app.state during lifespan startup.
    """
    return request.app.state.event_bus


def get_event_repository(session: AsyncSession = Depends(get_db)) -> EventRepository:
    """
    Dependency injector that initializes and returns an EventRepository instance.
    """
    return EventRepository(session)


def get_claim_extractor() -> ClaimExtractor:
    """
    Dependency injector for the ClaimExtractor service, initialized with core configuration.
    """
    return ClaimExtractor(
        api_url=settings.OLLAMA_API_URL,
        model_name=settings.LLM_MODEL
    )


def get_claim_repository(session: AsyncSession = Depends(get_db)) -> ClaimRepository:
    """
    Dependency injector that initializes and returns a ClaimRepository instance.
    """
    return ClaimRepository(session)


def get_claim_validator() -> ClaimValidator:
    """
    Dependency injector for the ClaimValidator service, initialized with core configuration.
    """
    return ClaimValidator(
        api_url=settings.OLLAMA_API_URL,
        model_name=settings.LLM_MODEL
    )


def get_validation_repository(session: AsyncSession = Depends(get_db)) -> ValidationRepository:
    """
    Dependency injector that initializes and returns a ValidationRepository instance.
    """
    return ValidationRepository(session)


def get_research_coordinator(
    llm_service=Depends(get_llm_service),
    search_service=Depends(get_search_service),
    scraper_service=Depends(get_scraper_service),
    claim_extractor=Depends(get_claim_extractor),
    validator=Depends(get_claim_validator),
    event_bus=Depends(get_event_bus),
    session_repo=Depends(get_session_repository),
    query_repo=Depends(get_query_repository),
    search_result_repo=Depends(get_search_result_repository),
    fetched_page_repo=Depends(get_fetched_page_repository),
    claim_repo=Depends(get_claim_repository),
    validation_repo=Depends(get_validation_repository),
) -> ResearchCoordinator:
    """
    Dependency injector for the ResearchCoordinator orchestration service.
    """
    telemetry = TelemetryService(session_maker=_telemetry_session_maker)
    return ResearchCoordinator(
        llm_service=llm_service,
        search_service=search_service,
        scraper_service=scraper_service,
        claim_extractor=claim_extractor,
        validator=validator,
        event_bus=event_bus,
        session_repo=session_repo,
        query_repo=query_repo,
        search_result_repo=search_result_repo,
        fetched_page_repo=fetched_page_repo,
        claim_repo=claim_repo,
        validation_repo=validation_repo,
        telemetry=telemetry,
    )


def get_page_understanding_service() -> PageUnderstandingService:
    """
    Dependency injector for the PageUnderstandingService, initialized with core configuration.
    """
    return PageUnderstandingService(
        api_url=settings.OLLAMA_API_URL,
        model_name=settings.LLM_MODEL
    )


def get_page_knowledge_repository(session: AsyncSession = Depends(get_db)) -> PageKnowledgeRepository:
    """
    Dependency injector that initializes and returns a PageKnowledgeRepository instance.
    """
    return PageKnowledgeRepository(session)


def get_knowledge_repository(session: AsyncSession = Depends(get_db)) -> KnowledgeRepository:
    """
    Dependency injector that initializes and returns a KnowledgeRepository instance.
    """
    return KnowledgeRepository(session)


def get_knowledge_builder_service() -> KnowledgeBuilderService:
    """
    Dependency injector for the KnowledgeBuilderService, initialized with core configuration.
    """
    return KnowledgeBuilderService(
        api_url=settings.OLLAMA_API_URL,
        model_name=settings.LLM_MODEL
    )


def get_gap_repository(session: AsyncSession = Depends(get_db)) -> GapRepository:
    """
    Dependency injector that initializes and returns a GapRepository instance.
    """
    return GapRepository(session)


def get_gap_discovery_service() -> GapDiscoveryService:
    """
    Dependency injector for the GapDiscoveryService, initialized with core configuration.
    """
    return GapDiscoveryService(
        api_url=settings.OLLAMA_API_URL,
        model_name=settings.LLM_MODEL
    )


def get_followup_query_repository(session: AsyncSession = Depends(get_db)) -> FollowupQueryRepository:
    """
    Dependency injector that initializes and returns a FollowupQueryRepository instance.
    """
    return FollowupQueryRepository(session)


def get_research_planner_service() -> ResearchPlannerV2:
    """
    Dependency injector for the ResearchPlannerV2, initialized with core configuration.
    """
    return ResearchPlannerV2(
        api_url=settings.OLLAMA_API_URL,
        model_name=settings.LLM_MODEL
    )


def get_strategy_repository(session: AsyncSession = Depends(get_db)) -> StrategyRepository:
    """
    Dependency injector that initializes and returns a StrategyRepository instance.
    """
    return StrategyRepository(session)


def get_strategy_learning_engine() -> StrategyLearningEngine:
    """
    Dependency injector for the StrategyLearningEngine service.
    """
    return StrategyLearningEngine(
        api_url=settings.OLLAMA_API_URL,
        model_name=settings.LLM_MODEL
    )


def get_iterative_research_coordinator(
    llm_service=Depends(get_llm_service),
    search_service=Depends(get_search_service),
    scraper_service=Depends(get_scraper_service),
    page_understanding_service=Depends(get_page_understanding_service),
    knowledge_builder_service=Depends(get_knowledge_builder_service),
    gap_discovery_service=Depends(get_gap_discovery_service),
    research_planner_service=Depends(get_research_planner_service),
    event_bus=Depends(get_event_bus),
    session_repo=Depends(get_session_repository),
    query_repo=Depends(get_query_repository),
    search_result_repo=Depends(get_search_result_repository),
    fetched_page_repo=Depends(get_fetched_page_repository),
    page_knowledge_repo=Depends(get_page_knowledge_repository),
    knowledge_repo=Depends(get_knowledge_repository),
    gap_repo=Depends(get_gap_repository),
    followup_repo=Depends(get_followup_query_repository),
    strategy_service=Depends(get_strategy_learning_engine),
    strategy_repo=Depends(get_strategy_repository),
    claim_repo=Depends(get_claim_repository),
    validation_repo=Depends(get_validation_repository),
    claim_extractor=Depends(get_claim_extractor),
    claim_validator=Depends(get_claim_validator),
) -> IterativeResearchCoordinator:
    """
    Dependency injector for the IterativeResearchCoordinator orchestration service.
    """
    telemetry = TelemetryService(session_maker=_telemetry_session_maker)
    return IterativeResearchCoordinator(
        llm_service=llm_service,
        search_service=search_service,
        scraper_service=scraper_service,
        page_understanding_service=page_understanding_service,
        knowledge_builder_service=knowledge_builder_service,
        gap_discovery_service=gap_discovery_service,
        research_planner_service=research_planner_service,
        event_bus=event_bus,
        session_repo=session_repo,
        query_repo=query_repo,
        search_result_repo=search_result_repo,
        fetched_page_repo=fetched_page_repo,
        page_knowledge_repo=page_knowledge_repo,
        knowledge_repo=knowledge_repo,
        gap_repo=gap_repo,
        followup_repo=followup_repo,
        claim_extractor=claim_extractor,
        claim_validator=claim_validator,
        strategy_service=strategy_service,
        strategy_repo=strategy_repo,
        claim_repo=claim_repo,
        validation_repo=validation_repo,
        telemetry=telemetry,
    )


