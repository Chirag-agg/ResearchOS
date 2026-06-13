import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.coordinator import (
    IterativeResearchRequest,
    IterativeResearchRunResult,
)
from app.services.iterative_coordinator import IterativeResearchCoordinator, IterativeCoordinatorError
from app.api.deps import get_iterative_research_coordinator

logger = logging.getLogger(__name__)
router = APIRouter()


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
