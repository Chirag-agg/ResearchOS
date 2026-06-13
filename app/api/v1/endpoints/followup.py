import logging
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.followup import (
    FollowupPlanningRequest,
    FollowupPlanningResponse,
    FollowupQueryRead,
    FollowupQuery,
)
from app.models.session import SessionStatus
from app.models.event import EventType
from app.events.bus import EventBus
from app.services.research_planner import ResearchPlannerV2, ResearchPlannerError
from app.repositories.session import SessionRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.gap import GapRepository
from app.repositories.followup import FollowupQueryRepository
from app.api.deps import (
    get_research_planner_service,
    get_session_repository,
    get_knowledge_repository,
    get_gap_repository,
    get_followup_query_repository,
    get_event_bus,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/research/plan-followups",
    response_model=FollowupPlanningResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate concrete follow-up research queries based on gaps"
)
async def plan_session_followups(
    payload: FollowupPlanningRequest,
    planner_service: ResearchPlannerV2 = Depends(get_research_planner_service),
    session_repo: SessionRepository = Depends(get_session_repository),
    knowledge_repo: KnowledgeRepository = Depends(get_knowledge_repository),
    gap_repo: GapRepository = Depends(get_gap_repository),
    followup_repo: FollowupQueryRepository = Depends(get_followup_query_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> FollowupPlanningResponse:
    """
    Generate followup research queries targeting identified knowledge gaps in a session.

    Flow:
    1. Validate session exists
    2. Load knowledge nodes, edges, and gaps for the session
    3. Set session status to running and publish FOLLOWUP_PLANNING_STARTED
    4. Call ResearchPlannerV2 to generate followup queries
    5. Persist FollowupQuery records to database
    6. Publish FOLLOWUP_QUERY_GENERATED for each query
    7. Update session status to completed and publish FOLLOWUP_PLANNING_COMPLETED and SESSION_COMPLETED
    """
    session_id = payload.session_id

    # 1. Validate session exists
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found."
        )

    # 2. Load context: nodes, edges, gaps
    nodes = await knowledge_repo.get_nodes_by_session(session_id)
    edges = await knowledge_repo.get_edges_by_session(session_id)
    gaps = await gap_repo.get_by_session(session_id)

    # 3. Set session status to running and publish FOLLOWUP_PLANNING_STARTED
    await session_repo.update_status(session_id, SessionStatus.RUNNING)
    await event_bus.publish(
        EventType.FOLLOWUP_PLANNING_STARTED,
        session_id=session_id,
        payload={
            "node_count": len(nodes),
            "edge_count": len(edges),
            "gap_count": len(gaps),
        },
    )

    try:
        # 4. Generate followup queries
        queries = await planner_service.generate_followup_queries(
            session_id=session_id,
            question=session.question,
            nodes=nodes,
            edges=edges,
            gaps=gaps
        )

        # 5. Persist followup queries
        persisted_queries = await followup_repo.create_many(queries)

        # 6. Publish FOLLOWUP_QUERY_GENERATED for each query
        for query in persisted_queries:
            await event_bus.publish(
                EventType.FOLLOWUP_QUERY_GENERATED,
                session_id=session_id,
                payload={
                    "query_id": str(query.id),
                    "query": query.query,
                    "priority": query.priority.value,
                }
            )

        # 7. Complete session and publish FOLLOWUP_PLANNING_COMPLETED and SESSION_COMPLETED
        await session_repo.update_status(session_id, SessionStatus.COMPLETED)

        await event_bus.publish(
            EventType.FOLLOWUP_PLANNING_COMPLETED,
            session_id=session_id,
            payload={
                "query_count": len(persisted_queries),
            }
        )
        await event_bus.publish(
            EventType.SESSION_COMPLETED,
            session_id=session_id,
            payload={"result": "queries_planned"}
        )

        # Construct response reads
        response_queries = [
            FollowupQueryRead(
                id=q.id,
                session_id=q.session_id,
                query=q.query,
                reason=q.reason,
                priority=q.priority,
                created_at=q.created_at,
            )
            for q in persisted_queries
        ]

        return FollowupPlanningResponse(queries=response_queries)

    except Exception as e:
        logger.error(f"Followup query planning session {session_id} failed: {e}", exc_info=True)
        await session_repo.update_status(session_id, SessionStatus.FAILED)

        await event_bus.publish(
            EventType.FOLLOWUP_PLANNING_FAILED,
            session_id=session_id,
            payload={"error": str(e)}
        )
        await event_bus.publish(
            EventType.SESSION_FAILED,
            session_id=session_id,
            payload={"error": str(e), "phase": "followup_planning"}
        )

        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if isinstance(e, ResearchPlannerError)
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"An error occurred during followup query planning: {e}"
        )
