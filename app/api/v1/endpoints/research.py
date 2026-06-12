from fastapi import APIRouter, Depends, HTTPException, status
from app.models.research import ResearchQuestion, ResearchQueries
from app.services.planner import PlannerService, PlannerError
from app.api.deps import get_planner_service

router = APIRouter()


@router.post("/research", response_model=ResearchQueries, status_code=status.HTTP_200_OK)
async def plan_research(
    payload: ResearchQuestion,
    planner_service: PlannerService = Depends(get_planner_service)
) -> ResearchQueries:
    """
    Exposes the query generation planning phase. Converts a single research
    question into exactly 5 high-quality search query strings.
    """
    try:
        queries = await planner_service.generate_queries(payload.question)
        return ResearchQueries(queries=queries)
    except PlannerError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during query generation planning: {e}"
        )
