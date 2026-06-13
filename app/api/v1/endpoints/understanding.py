import logging
import json
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.page_knowledge import (
    PageAnalysisRequest,
    PageAnalysisResponse,
    PageKnowledgeRead,
    PageKnowledge,
)
from app.models.session import SessionStatus
from app.models.event import EventType
from app.events.bus import EventBus
from app.services.page_understanding import PageUnderstandingService, PageUnderstandingError
from app.repositories.session import SessionRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.page_knowledge import PageKnowledgeRepository
from app.api.deps import (
    get_page_understanding_service,
    get_page_knowledge_repository,
    get_session_repository,
    get_fetched_page_repository,
    get_event_bus,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/research/analyze-pages",
    response_model=PageAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Capture structured page understanding for fetched pages in a session"
)
async def analyze_session_pages(
    payload: PageAnalysisRequest,
    understanding_service: PageUnderstandingService = Depends(get_page_understanding_service),
    session_repo: SessionRepository = Depends(get_session_repository),
    fetched_page_repo: FetchedPageRepository = Depends(get_fetched_page_repository),
    knowledge_repo: PageKnowledgeRepository = Depends(get_page_knowledge_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> PageAnalysisResponse:
    """
    Generate and persist structured understanding summaries, key points, topics,
    entities, and importance scores for successfully fetched pages in a session.
    """
    session_id = payload.session_id

    # 1. Validate session exists
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found."
        )

    # 2. Load fetched pages for session
    pages = await fetched_page_repo.get_by_session(session_id)
    
    # 3. Filter successful pages
    successful_pages = [p for p in pages if p.fetch_status == "success"]
    if not successful_pages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No successfully fetched pages found for this session. Run fetch first."
        )

    # Limit page execution to prevent local CPU overload on Ollama
    from app.core.config import settings
    successful_pages = successful_pages[:settings.MAX_CLAIM_EXTRACTION_PAGES]

    # 4. Set session status to running and publish PAGE_ANALYSIS_STARTED
    await session_repo.update_status(session_id, SessionStatus.RUNNING)
    await event_bus.publish(
        EventType.PAGE_ANALYSIS_STARTED,
        session_id=session_id,
        payload={"page_count": len(successful_pages)},
    )

    try:
        session_knowledges: List[PageKnowledge] = []

        # 5. Extract structured understanding for each page
        for page in successful_pages:
            res = await understanding_service.analyze_page(page.content)

            knowledge = PageKnowledge(
                page_id=page.id,
                session_id=session_id,
                summary=res["summary"],
                key_points=json.dumps(res["key_points"]),
                main_topics=json.dumps(res["main_topics"]),
                entities=json.dumps(res["entities"]),
                importance_score=res["importance_score"],
            )
            session_knowledges.append(knowledge)

        # 6. Persist knowledges
        persisted_knowledges = await knowledge_repo.create_many(session_knowledges)

        # Publish PAGE_ANALYZED for each page
        for k in persisted_knowledges:
            await event_bus.publish(
                EventType.PAGE_ANALYZED,
                session_id=session_id,
                payload={
                    "page_id": str(k.page_id),
                    "knowledge_id": str(k.id),
                    "summary_preview": k.summary[:100],
                    "importance_score": k.importance_score,
                }
            )

        # 7. Complete session and publish events
        await session_repo.update_status(session_id, SessionStatus.COMPLETED)
        
        await event_bus.publish(
            EventType.PAGE_ANALYSIS_COMPLETED,
            session_id=session_id,
            payload={
                "total_analyzed": len(persisted_knowledges),
            }
        )
        await event_bus.publish(
            EventType.SESSION_COMPLETED,
            session_id=session_id,
            payload={"result": "pages_analyzed"}
        )

        response_knowledges = [
            PageKnowledgeRead(
                id=k.id,
                page_id=k.page_id,
                session_id=k.session_id,
                summary=k.summary,
                key_points=json.loads(k.key_points),
                main_topics=json.loads(k.main_topics),
                entities=json.loads(k.entities),
                importance_score=k.importance_score,
                created_at=k.created_at,
            )
            for k in persisted_knowledges
        ]

        return PageAnalysisResponse(knowledges=response_knowledges)

    except Exception as e:
        logger.error(f"Page analysis session {session_id} failed: {e}", exc_info=True)
        await session_repo.update_status(session_id, SessionStatus.FAILED)
        
        await event_bus.publish(
            EventType.PAGE_ANALYSIS_FAILED,
            session_id=session_id,
            payload={"error": str(e)}
        )
        await event_bus.publish(
            EventType.SESSION_FAILED,
            session_id=session_id,
            payload={"error": str(e), "phase": "page_analysis"}
        )

        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if isinstance(e, PageUnderstandingError)
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"An error occurred during page analysis: {e}"
        )
