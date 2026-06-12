from uuid import UUID
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.session import ResearchSession, SessionStatus
from app.models.base import get_utc_now


class SessionRepository:
    """
    Repository class providing access to ResearchSession persistence storage using AsyncSession.
    """
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(self, question: str) -> ResearchSession:
        """
        Creates a new ResearchSession and persists it.
        """
        db_session = ResearchSession(question=question)
        self.session.add(db_session)
        await self.session.commit()
        await self.session.refresh(db_session)
        return db_session

    async def get_session(self, session_id: UUID) -> Optional[ResearchSession]:
        """
        Retrieves a single ResearchSession by ID.
        """
        # Async session get by primary key
        return await self.session.get(ResearchSession, session_id)

    async def list_sessions(self) -> List[ResearchSession]:
        """
        Retrieves all sessions ordered by creation date (descending).
        """
        statement = select(ResearchSession).order_by(ResearchSession.created_at.desc())
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def update_status(self, session_id: UUID, status: SessionStatus) -> Optional[ResearchSession]:
        """
        Updates the status of a specific ResearchSession and updates the updated_at timestamp.
        """
        db_session = await self.get_session(session_id)
        if not db_session:
            return None
            
        db_session.status = status
        db_session.updated_at = get_utc_now()
        
        self.session.add(db_session)
        await self.session.commit()
        await self.session.refresh(db_session)
        return db_session
