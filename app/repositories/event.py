from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.event import ResearchEvent, EventType


class EventRepository:
    """
    Repository class providing access to ResearchEvent persistence storage.
    Handles creation and retrieval of pipeline events.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_event(self, event: ResearchEvent) -> ResearchEvent:
        """
        Persist a single ResearchEvent record.
        """
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def get_session_events(self, session_id: UUID) -> List[ResearchEvent]:
        """
        Retrieve all events for a research session, ordered chronologically.
        """
        statement = (
            select(ResearchEvent)
            .where(ResearchEvent.session_id == session_id)
            .order_by(ResearchEvent.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_events_by_type(
        self, event_type: EventType, session_id: UUID | None = None
    ) -> List[ResearchEvent]:
        """
        Retrieve events filtered by event type, optionally scoped to a session.
        """
        statement = select(ResearchEvent).where(
            ResearchEvent.event_type == event_type
        )
        if session_id is not None:
            statement = statement.where(ResearchEvent.session_id == session_id)

        statement = statement.order_by(ResearchEvent.created_at.asc())
        result = await self.session.execute(statement)
        return list(result.scalars().all())
