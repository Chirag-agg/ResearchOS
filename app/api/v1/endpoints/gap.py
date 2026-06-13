import logging
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.gap import (
    GapDiscoveryRequest,
    GapDiscoveryResponse,
    GapRead,
    ResearchGap,
)
from app.models.session import SessionStatus
from app.models.event import EventType
from app.events.bus import EventBus
from app.services.gap_discovery import GapDiscoveryService, GapDiscoveryError
from app.repositories.session import SessionRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.gap import GapRepository
from app.api.deps import (
    get_gap_discovery_service,
    get_session_repository,
    get_knowledge_repository,
    get_gap_repository,
    get_event_bus,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/research/discover-gaps",
    response_model=GapDiscoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Identify research knowledge gaps in the session"
)
async def discover_session_gaps(
    payload: GapDiscoveryRequest,
    gap_discovery_service: GapDiscoveryService = Depends(get_gap_discovery_service),
    session_repo: SessionRepository = Depends(get_session_repository),
    knowledge_repo: KnowledgeRepository = Depends(get_knowledge_repository),
    gap_repo: GapRepository = Depends(get_gap_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> GapDiscoveryResponse:
    """
    Identify missing research knowledge areas based on the session's question and knowledge graph.

    Flow:
    1. Validate session exists
    2. Load existing knowledge nodes and edges for the session
    3. Set session status to running and publish GAP_DISCOVERY_STARTED
    4. Call GapDiscoveryService to analyze coverage and identify gaps
    5. Persist ResearchGap records to database
    6. Publish GAP_FOUND for each gap
    7. Update session status to completed and publish GAP_DISCOVERY_COMPLETED and SESSION_COMPLETED
    """
    session_id = payload.session_id

    # 1. Validate session exists
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found."
        )

    # 2. Load knowledge nodes and edges
    nodes = await knowledge_repo.get_nodes_by_session(session_id)
    edges = await knowledge_repo.get_edges_by_session(session_id)

    # 3. Set session status to running and publish GAP_DISCOVERY_STARTED
    await session_repo.update_status(session_id, SessionStatus.RUNNING)
    await event_bus.publish(
        EventType.GAP_DISCOVERY_STARTED,
        session_id=session_id,
        payload={"node_count": len(nodes), "edge_count": len(edges)},
    )

    try:
        # 4. Discover gaps
        discovery_result = await gap_discovery_service.find_research_gaps(
            session_id=session_id,
            question=session.question,
            nodes=nodes,
            edges=edges
        )

        # 5. Persist gaps
        persisted_gaps = await gap_repo.create_many(discovery_result["gaps"])

        # 6. Publish GAP_FOUND for each gap
        for gap in persisted_gaps:
            await event_bus.publish(
                EventType.GAP_FOUND,
                session_id=session_id,
                payload={
                    "gap_id": str(gap.id),
                    "topic": gap.topic,
                    "priority": gap.priority.value,
                }
            )

        # 7. Complete session and publish GAP_DISCOVERY_COMPLETED and SESSION_COMPLETED
        await session_repo.update_status(session_id, SessionStatus.COMPLETED)

        await event_bus.publish(
            EventType.GAP_DISCOVERY_COMPLETED,
            session_id=session_id,
            payload={
                "known_count": len(discovery_result["known_topics"]),
                "missing_count": len(persisted_gaps),
                "confidence": discovery_result["confidence"],
            }
        )
        await event_bus.publish(
            EventType.SESSION_COMPLETED,
            session_id=session_id,
            payload={"result": "gaps_discovered"}
        )

        # Construct response reads
        response_gaps = [
            GapRead(
                id=g.id,
                session_id=g.session_id,
                topic=g.topic,
                reason=g.reason,
                priority=g.priority,
                created_at=g.created_at,
            )
            for g in persisted_gaps
        ]

        return GapDiscoveryResponse(
            known_topics=discovery_result["known_topics"],
            missing_topics=discovery_result["missing_topics"],
            confidence=discovery_result["confidence"],
            gaps=response_gaps,
        )

    except Exception as e:
        logger.error(f"Gap discovery session {session_id} failed: {e}", exc_info=True)
        await session_repo.update_status(session_id, SessionStatus.FAILED)

        await event_bus.publish(
            EventType.GAP_DISCOVERY_FAILED,
            session_id=session_id,
            payload={"error": str(e)}
        )
        await event_bus.publish(
            EventType.SESSION_FAILED,
            session_id=session_id,
            payload={"error": str(e), "phase": "gap_discovery"}
        )

        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if isinstance(e, GapDiscoveryError)
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"An error occurred during gap discovery: {e}"
        )
