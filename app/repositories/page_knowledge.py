from uuid import UUID
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.page_knowledge import PageKnowledge


class PageKnowledgeRepository:
    """
    Repository class providing access to PageKnowledge persistence storage.
    Handles batch creation and lookup of extracted page understandings.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_many(self, knowledges: List[PageKnowledge]) -> List[PageKnowledge]:
        """
        Persist a batch of PageKnowledge records in a single transaction.
        """
        if not knowledges:
            return []

        for k in knowledges:
            self.session.add(k)
        await self.session.commit()

        for k in knowledges:
            await self.session.refresh(k)

        return knowledges

    async def get_by_page(self, page_id: UUID) -> Optional[PageKnowledge]:
        """
        Retrieve page knowledge associated with a specific fetched page.
        """
        statement = select(PageKnowledge).where(PageKnowledge.page_id == page_id)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_by_session(self, session_id: UUID) -> List[PageKnowledge]:
        """
        Retrieve all page knowledge records associated with a research session.
        """
        statement = (
            select(PageKnowledge)
            .where(PageKnowledge.session_id == session_id)
            .order_by(PageKnowledge.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
