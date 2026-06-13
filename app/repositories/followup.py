from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.followup import FollowupQuery


class FollowupQueryRepository:
    """
    Repository class providing access to FollowupQuery persistence storage.
    Handles bulk creation and retrieval by session.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_many(self, queries: List[FollowupQuery]) -> List[FollowupQuery]:
        """
        Persist a batch of FollowupQuery records in a single transaction.
        """
        if not queries:
            return []

        for q in queries:
            self.session.add(q)
        await self.session.commit()

        for q in queries:
            await self.session.refresh(q)

        return queries

    async def get_by_session(self, session_id: UUID) -> List[FollowupQuery]:
        """
        Retrieve all followup queries associated with a research session.
        """
        statement = (
            select(FollowupQuery)
            .where(FollowupQuery.session_id == session_id)
            .order_by(FollowupQuery.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
