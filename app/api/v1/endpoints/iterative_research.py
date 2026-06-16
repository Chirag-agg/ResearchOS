import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.db import async_session_maker
from app.models.coordinator import (
    IterativeResearchRequest,
    IterativeResearchRunResult,
    IterativeResearchLaunchResponse,
)
from app.repositories.claim import ClaimRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.followup import FollowupQueryRepository
from app.repositories.gap import GapRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.page_knowledge import PageKnowledgeRepository
from app.repositories.query import QueryRepository
from app.repositories.search_result import SearchResultRepository
from app.repositories.session import SessionRepository
from app.repositories.strategy import StrategyRepository
from app.repositories.validation import ValidationRepository
from app.services.gap_discovery import GapDiscoveryService
from app.services.knowledge_builder import KnowledgeBuilderService
from app.services.llm import LLMService
from app.services.page_understanding import PageUnderstandingService
from app.services.research_planner import ResearchPlannerV2
from app.services.scraper import ScraperService
from app.services.search import SearchService
from app.services.strategy_learning import StrategyLearningEngine
from app.services.claim_extractor import ClaimExtractor
from app.services.claim_validator import ClaimValidator
from app.services.iterative_coordinator import IterativeResearchCoordinator, IterativeCoordinatorError
from app.api.deps import get_event_bus, get_iterative_research_coordinator, get_session_repository

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_service_kwargs() -> dict:
    return {
        "llm_service": LLMService(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL),
        "search_service": SearchService(api_url=settings.SEARXNG_URL),
        "scraper_service": ScraperService(
            timeout_ms=settings.PLAYWRIGHT_TIMEOUT_MS,
            html_storage_dir=settings.HTML_STORAGE_DIR,
        ),
        "page_understanding_service": PageUnderstandingService(
            api_url=settings.OLLAMA_API_URL,
            model_name=settings.LLM_MODEL,
        ),
        "knowledge_builder_service": KnowledgeBuilderService(
            api_url=settings.OLLAMA_API_URL,
            model_name=settings.LLM_MODEL,
        ),
        "gap_discovery_service": GapDiscoveryService(
            api_url=settings.OLLAMA_API_URL,
            model_name=settings.LLM_MODEL,
        ),
        "research_planner_service": ResearchPlannerV2(
            api_url=settings.OLLAMA_API_URL,
            model_name=settings.LLM_MODEL,
        ),
        "strategy_service": StrategyLearningEngine(
            api_url=settings.OLLAMA_API_URL,
            model_name=settings.LLM_MODEL,
        ),
        "claim_extractor": ClaimExtractor(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL),
        "claim_validator": ClaimValidator(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL),
    }


async def _run_iterative_research_background(
    session_id: UUID,
    question: str,
    max_rounds: int | None,
    confidence_threshold: float | None,
    event_bus,
    telemetry,
) -> None:
    try:
        async with async_session_maker() as session:
            coordinator = IterativeResearchCoordinator(
                **_build_service_kwargs(),
                event_bus=event_bus,
                session_repo=SessionRepository(session),
                query_repo=QueryRepository(session),
                search_result_repo=SearchResultRepository(session),
                fetched_page_repo=FetchedPageRepository(session),
                page_knowledge_repo=PageKnowledgeRepository(session),
                knowledge_repo=KnowledgeRepository(session),
                gap_repo=GapRepository(session),
                followup_repo=FollowupQueryRepository(session),
                strategy_repo=StrategyRepository(session),
                claim_repo=ClaimRepository(session),
                validation_repo=ValidationRepository(session),
                telemetry=telemetry,
            )
            await coordinator.run_iterative_research(
                question=question,
                max_rounds=max_rounds,
                confidence_threshold=confidence_threshold,
                session_id=session_id,
            )
    except Exception as exc:
        logger.error("Background iterative research failed for session %s: %s", session_id, exc, exc_info=True)


@router.post(
    "/research/run-iterative",
    response_model=IterativeResearchRunResult,
    status_code=status.HTTP_200_OK,
    summary="Execute multi-round iterative autonomous research"
)
async def run_iterative_research_loop(
    payload: IterativeResearchRequest,
    coordinator: IterativeResearchCoordinator = Depends(get_iterative_research_coordinator),
) -> IterativeResearchRunResult:
    """
    Triggers the multi-round autonomous research pipeline loop.
    Repeatedly searches, fetches pages, updates knowledge, evaluates coverage gaps,
    and refines subsequent search queries until stop conditions are met.
    """
    try:
        result = await coordinator.run_iterative_research(
            question=payload.question,
            max_rounds=payload.max_rounds,
            confidence_threshold=payload.confidence_threshold,
        )
        return result
    except IterativeCoordinatorError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Iterative research loop failed: {e}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in iterative research endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during iterative research: {e}"
        )


@router.post(
    "/research/run-iterative/start",
    response_model=IterativeResearchLaunchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start iterative research in the background",
)
async def start_iterative_research_loop(
    payload: IterativeResearchRequest,
    request: Request,
    event_bus=Depends(get_event_bus),
    session_repo: SessionRepository = Depends(get_session_repository),
) -> IterativeResearchLaunchResponse:
    """
    Starts the iterative pipeline without waiting for completion so the UI can
    attach to live telemetry while the run is still in progress.
    """
    if payload.session_id is not None:
        session = await session_repo.get_session(payload.session_id)
        if session is None:
            session = await session_repo.create_session(question=payload.question)
    else:
        session = await session_repo.create_session(question=payload.question)

    telemetry = getattr(request.app.state, "telemetry_service", None)
    if telemetry is None:
        from app.services.telemetry import TelemetryService

        telemetry = TelemetryService(session_maker=async_session_maker)

    asyncio.create_task(
        _run_iterative_research_background(
            session_id=session.id,
            question=payload.question,
            max_rounds=payload.max_rounds,
            confidence_threshold=payload.confidence_threshold,
            event_bus=event_bus,
            telemetry=telemetry,
        )
    )

    return IterativeResearchLaunchResponse(
        session_id=session.id,
        question=payload.question,
        status="running",
    )
