from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.session import SessionCreate, SessionRead
from app.repositories.session import SessionRepository
from app.api.deps import get_session_repository

router = APIRouter()


@router.post(
    "/sessions",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new research session"
)
async def create_research_session(
    payload: SessionCreate,
    repo: SessionRepository = Depends(get_session_repository)
) -> SessionRead:
    """
    Creates a new research session with the requested question.
    Initializes status as 'pending'.
    """
    try:
        session = await repo.create_session(question=payload.question)
        return session
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create research session: {e}"
        )


@router.get(
    "/sessions",
    response_model=List[SessionRead],
    status_code=status.HTTP_200_OK,
    summary="List all research sessions"
)
async def list_research_sessions(
    repo: SessionRepository = Depends(get_session_repository)
) -> List[SessionRead]:
    """
    Lists all past and present research sessions, sorted by created date descending.
    """
    try:
        sessions = await repo.list_sessions()
        return sessions
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve sessions: {e}"
        )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionRead,
    status_code=status.HTTP_200_OK,
    summary="Get research session by ID"
)
async def get_research_session(
    session_id: UUID,
    repo: SessionRepository = Depends(get_session_repository)
) -> SessionRead:
    """
    Retrieves the details of a specific research session by its unique ID.
    Throws 404 if not found.
    """
    try:
        session = await repo.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Research session with ID {session_id} not found."
            )
        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch research session details: {e}"
        )
