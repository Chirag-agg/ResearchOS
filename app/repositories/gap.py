from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.gap import ResearchGap


class GapRepository:
    """
    Repository class providing access to ResearchGap persistence storage.
    Handles bulk creation and retrieval by session.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_many(self, gaps: List[ResearchGap]) -> List[ResearchGap]:
        """
        Persist a batch of ResearchGap records in a single transaction.
        """
        if not gaps:
            return []

        for gap in gaps:
            self.session.add(gap)
        await self.session.commit()

        for gap in gaps:
            await self.session.refresh(gap)

        return gaps

    async def get_by_session(self, session_id: UUID) -> List[ResearchGap]:
        """
        Retrieve all research gaps associated with a research session.
        """
        statement = (
            select(ResearchGap)
            .where(ResearchGap.session_id == session_id)
            .order_by(ResearchGap.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
