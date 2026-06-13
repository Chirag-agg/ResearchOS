import logging
import json
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.strategy import (
    StrategyLearnRequest,
    StrategyConsultRequest,
    StrategyMemoryRead,
    StrategyAdaptationResponse,
)
from app.services.strategy_learning import StrategyLearningEngine
from app.repositories.session import SessionRepository
from app.repositories.query import QueryRepository
from app.repositories.search_result import SearchResultRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.claim import ClaimRepository
from app.repositories.validation import ValidationRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.strategy import StrategyRepository
from app.events.bus import EventBus
from app.api.deps import (
    get_strategy_learning_engine,
    get_session_repository,
    get_query_repository,
    get_search_result_repository,
    get_fetched_page_repository,
    get_claim_repository,
    get_validation_repository,
    get_knowledge_repository,
    get_strategy_repository,
    get_event_bus,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["strategy"])


@router.post(
    "/strategy/learn",
    response_model=StrategyMemoryRead,
    status_code=status.HTTP_200_OK,
    summary="Learn strategy patterns from a completed research session"
)
async def learn_session_strategy(
    payload: StrategyLearnRequest,
    strategy_service: StrategyLearningEngine = Depends(get_strategy_learning_engine),
    session_repo: SessionRepository = Depends(get_session_repository),
    query_repo: QueryRepository = Depends(get_query_repository),
    search_result_repo: SearchResultRepository = Depends(get_search_result_repository),
    fetched_page_repo: FetchedPageRepository = Depends(get_fetched_page_repository),
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    validation_repo: ValidationRepository = Depends(get_validation_repository),
    knowledge_repo: KnowledgeRepository = Depends(get_knowledge_repository),
    strategy_repo: StrategyRepository = Depends(get_strategy_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> StrategyMemoryRead:
    """
    Analyzes session outcomes and persists strategy memory for similar future question types.
    """
    session_id = payload.session_id

    # 1. Validate session exists
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found."
        )

    try:
        memory = await strategy_service.learn_strategy(
            session_id=session_id,
            question=session.question,
            session_repo=session_repo,
            query_repo=query_repo,
            search_result_repo=search_result_repo,
            fetched_page_repo=fetched_page_repo,
            claim_repo=claim_repo,
            validation_repo=validation_repo,
            knowledge_repo=knowledge_repo,
            strategy_repo=strategy_repo,
            event_bus=event_bus
        )

        return StrategyMemoryRead(
            id=memory.id,
            question_type=memory.question_type,
            successful_queries=json.loads(memory.successful_queries),
            successful_domains=json.loads(memory.successful_domains),
            research_outcomes=json.loads(memory.research_outcomes),
            created_at=memory.created_at
        )

    except Exception as e:
        logger.error(f"Strategy learning failed for session {session_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Strategy learning failed: {e}"
        )


@router.post(
    "/strategy/consult",
    response_model=StrategyAdaptationResponse,
    status_code=status.HTTP_200_OK,
    summary="Consult strategy memories to adapt query generation"
)
async def consult_strategy_adaptation(
    payload: StrategyConsultRequest,
    strategy_service: StrategyLearningEngine = Depends(get_strategy_learning_engine),
    strategy_repo: StrategyRepository = Depends(get_strategy_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> StrategyAdaptationResponse:
    """
    Returns search query and domain adaptation guidelines matching a question type.
    """
    try:
        adaptation = await strategy_service.consult_and_adapt(
            question=payload.question,
            strategy_repo=strategy_repo,
            event_bus=event_bus
        )

        return StrategyAdaptationResponse(
            question_type=adaptation["question_type"],
            adapted_instructions=adaptation["adapted_instructions"],
            successful_queries=adaptation["successful_queries"],
            successful_domains=adaptation["successful_domains"]
        )

    except Exception as e:
        logger.error(f"Strategy consultation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Strategy consultation failed: {e}"
        )
