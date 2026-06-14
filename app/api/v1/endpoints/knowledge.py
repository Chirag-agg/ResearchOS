import logging
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.knowledge import (
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    NodeRead,
    EdgeRead,
    KnowledgeNode,
    KnowledgeEdge,
)
from app.models.session import SessionStatus
from app.models.event import EventType
from app.events.bus import EventBus
from app.services.knowledge_builder import KnowledgeBuilderService, KnowledgeBuilderError
from app.repositories.session import SessionRepository
from app.repositories.page_knowledge import PageKnowledgeRepository
from app.repositories.knowledge import KnowledgeRepository
from app.api.deps import (
    get_knowledge_builder_service,
    get_session_repository,
    get_page_knowledge_repository,
    get_knowledge_repository,
    get_event_bus,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/research/build-knowledge",
    response_model=KnowledgeBuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Synthesize page knowledge records into a unified Knowledge Graph"
)
async def build_session_knowledge(
    payload: KnowledgeBuildRequest,
    knowledge_builder: KnowledgeBuilderService = Depends(get_knowledge_builder_service),
    session_repo: SessionRepository = Depends(get_session_repository),
    page_knowledge_repo: PageKnowledgeRepository = Depends(get_page_knowledge_repository),
    knowledge_repo: KnowledgeRepository = Depends(get_knowledge_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> KnowledgeBuildResponse:
    """
    Synthesize all extracted PageKnowledge records for a session into a unified Knowledge Graph of concepts and edges.

    Flow:
    1. Validate session exists
    2. Load extracted page knowledge records for the session
    3. Verify there is at least one page knowledge record to synthesize
    4. Set session status to running and publish KNOWLEDGE_BUILD_STARTED
    5. Call KnowledgeBuilderService to extract concepts and edges
    6. Persist KnowledgeNode and KnowledgeEdge records to database
    7. Publish KNOWLEDGE_NODE_CREATED for each concept
    8. Update session status to completed and publish KNOWLEDGE_BUILD_COMPLETED and SESSION_COMPLETED
    """
    session_id = payload.session_id

    # 1. Validate session exists
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found."
        )

    # 2. Load extracted page knowledge records for the session
    page_knowledges = await page_knowledge_repo.get_by_session(session_id)

    # 3. Verify there is at least one page knowledge record
    if not page_knowledges:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No page knowledge records found for this session. Analyze pages first."
        )

    # 4. Set session status to running and publish KNOWLEDGE_BUILD_STARTED
    await session_repo.update_status(session_id, SessionStatus.RUNNING)
    await event_bus.publish(
        EventType.KNOWLEDGE_BUILD_STARTED,
        session_id=session_id,
        payload={"page_knowledge_count": len(page_knowledges)},
    )

    try:
        # 5. Extract concepts and edges
        nodes_list, edges_list = await knowledge_builder.build_knowledge_graph(
            session_id, page_knowledges
        )

        # 6. Persist records
        persisted_nodes = await knowledge_repo.create_nodes(nodes_list)
        persisted_edges = await knowledge_repo.create_edges(edges_list)

        # 7. Publish KNOWLEDGE_NODE_CREATED for each node
        for node in persisted_nodes:
            await event_bus.publish(
                EventType.KNOWLEDGE_NODE_CREATED,
                session_id=session_id,
                payload={
                    "node_id": str(node.id),
                    "concept": node.concept,
                    "confidence": node.confidence,
                    "source_count": node.source_count,
                }
            )

        # 8. Complete session and publish KNOWLEDGE_BUILD_COMPLETED and SESSION_COMPLETED
        await session_repo.update_status(session_id, SessionStatus.COMPLETED)

        await event_bus.publish(
            EventType.KNOWLEDGE_BUILD_COMPLETED,
            session_id=session_id,
            payload={
                "nodes_count": len(persisted_nodes),
                "edges_count": len(persisted_edges),
            }
        )
        await event_bus.publish(
            EventType.SESSION_COMPLETED,
            session_id=session_id,
            payload={"result": "knowledge_built"}
        )

        # Construct response reads
        response_nodes = [
            NodeRead(
                id=n.id,
                session_id=n.session_id,
                concept=n.concept,
                description=n.description,
                confidence=n.confidence,
                source_count=n.source_count,
                created_at=n.created_at,
            )
            for n in persisted_nodes
        ]

        response_edges = [
            EdgeRead(
                id=e.id,
                session_id=e.session_id,
                source_node=e.source_node,
                target_node=e.target_node,
                relationship=e.relationship,
                created_at=e.created_at,
            )
            for e in persisted_edges
        ]

        return KnowledgeBuildResponse(nodes=response_nodes, edges=response_edges)

    except Exception as e:
        logger.error(f"Knowledge base building session {session_id} failed: {e}", exc_info=True)
        await session_repo.update_status(session_id, SessionStatus.FAILED)

        await event_bus.publish(
            EventType.KNOWLEDGE_BUILD_FAILED,
            session_id=session_id,
            payload={"error": str(e)}
        )
        await event_bus.publish(
            EventType.SESSION_FAILED,
            session_id=session_id,
            payload={"error": str(e), "phase": "knowledge_build"}
        )

        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if isinstance(e, KnowledgeBuilderError)
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"An error occurred during knowledge base building: {e}"
        )


@router.get(
    "/research/{session_id}/knowledge",
    response_model=KnowledgeBuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the synthesized Knowledge Graph for a session"
)
async def get_session_knowledge(
    session_id: str,
    knowledge_repo = Depends(get_knowledge_repository),
) -> KnowledgeBuildResponse:
    try:
        from uuid import UUID
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    nodes = await knowledge_repo.get_nodes_by_session(session_uuid)
    edges = await knowledge_repo.get_edges_by_session(session_uuid)

    response_nodes = [
        NodeRead(
            id=n.id,
            session_id=n.session_id,
            concept=n.concept,
            description=n.description,
            confidence=n.confidence,
            source_count=n.source_count,
            created_at=n.created_at,
        )
        for n in nodes
    ]

    response_edges = [
        EdgeRead(
            id=e.id,
            session_id=e.session_id,
            source_node=e.source_node,
            target_node=e.target_node,
            relationship=e.relationship,
            created_at=e.created_at,
        )
        for e in edges
    ]

    return KnowledgeBuildResponse(nodes=response_nodes, edges=response_edges)

