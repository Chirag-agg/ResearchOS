import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.event import EventRead, EventListResponse
from app.repositories.event import EventRepository
from app.repositories.session import SessionRepository
from app.api.deps import get_event_repository, get_session_repository

router = APIRouter()


@router.get(
    "/sessions/{session_id}/events",
    response_model=EventListResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve chronological event history for a research session",
)
async def get_session_events(
    session_id: UUID,
    session_repo: SessionRepository = Depends(get_session_repository),
    event_repo: EventRepository = Depends(get_event_repository),
) -> EventListResponse:
    """
    Returns the complete, chronologically ordered event history for a session.
    Every pipeline action that published an event appears here.
    """
    # Validate session exists
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found.",
        )

    events = await event_repo.get_session_events(session_id)

    event_reads = []
    for e in events:
        # Deserialize payload_json back to dict for the response
        payload = None
        if e.payload_json:
            try:
                payload = json.loads(e.payload_json)
            except (json.JSONDecodeError, TypeError):
                payload = {"raw": e.payload_json}

        event_reads.append(
            EventRead(
                id=e.id,
                session_id=e.session_id,
                step_id=e.step_id,
                event_type=e.event_type,
                payload=payload,
                timestamp=e.created_at,
            )
        )

    return EventListResponse(
        session_id=session_id,
        total_events=len(event_reads),
        events=event_reads,
    )
