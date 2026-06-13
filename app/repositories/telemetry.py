import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.telemetry import TelemetryEvent, TelemetryStage, TelemetryEventType

logger = logging.getLogger(__name__)


class TelemetryRepository:
    """
    Repository for persisting and querying TelemetryEvent records.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, event: TelemetryEvent) -> TelemetryEvent:
        """Persist a single telemetry event."""
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def create_many(self, events: List[TelemetryEvent]) -> List[TelemetryEvent]:
        """Persist multiple telemetry events in a single transaction."""
        for event in events:
            self.session.add(event)
        await self.session.commit()
        for event in events:
            await self.session.refresh(event)
        return events

    async def get_by_session(self, session_id: UUID) -> List[TelemetryEvent]:
        """Retrieve all telemetry events for a session, ordered chronologically."""
        stmt = (
            select(TelemetryEvent)
            .where(TelemetryEvent.session_id == session_id)
            .order_by(TelemetryEvent.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_stage(
        self, session_id: UUID, stage: TelemetryStage
    ) -> List[TelemetryEvent]:
        """Retrieve telemetry events for a specific stage."""
        stmt = (
            select(TelemetryEvent)
            .where(
                TelemetryEvent.session_id == session_id,
                TelemetryEvent.stage == stage,
            )
            .order_by(TelemetryEvent.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_event_type(
        self, session_id: UUID, event_type: TelemetryEventType
    ) -> List[TelemetryEvent]:
        """Retrieve telemetry events of a specific type."""
        stmt = (
            select(TelemetryEvent)
            .where(
                TelemetryEvent.session_id == session_id,
                TelemetryEvent.event_type == event_type,
            )
            .order_by(TelemetryEvent.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest(
        self, session_id: UUID, limit: int = 1
    ) -> List[TelemetryEvent]:
        """Retrieve the most recent telemetry events for a session."""
        stmt = (
            select(TelemetryEvent)
            .where(TelemetryEvent.session_id == session_id)
            .order_by(TelemetryEvent.timestamp.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_llm_calls(self, session_id: UUID) -> List[TelemetryEvent]:
        """Retrieve all LLM call completion events for a session."""
        stmt = (
            select(TelemetryEvent)
            .where(
                TelemetryEvent.session_id == session_id,
                TelemetryEvent.event_type == TelemetryEventType.LLM_CALL_COMPLETED,
            )
            .order_by(TelemetryEvent.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_round(
        self, session_id: UUID, research_round: int
    ) -> List[TelemetryEvent]:
        """Retrieve telemetry events for a specific research round."""
        stmt = (
            select(TelemetryEvent)
            .where(
                TelemetryEvent.session_id == session_id,
                TelemetryEvent.research_round == research_round,
            )
            .order_by(TelemetryEvent.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
