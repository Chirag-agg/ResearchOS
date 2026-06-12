from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.query import GeneratedQuery


class QueryRepository:
    """
    Repository class providing access to GeneratedQuery persistence storage.
    """
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_query(self, session_id: UUID, query_text: str) -> GeneratedQuery:
        """
        Creates and persists a single GeneratedQuery.
        """
        db_query = GeneratedQuery(session_id=session_id, query_text=query_text)
        self.session.add(db_query)
        await self.session.commit()
        await self.session.refresh(db_query)
        return db_query

    async def get_by_session(self, session_id: UUID) -> List[GeneratedQuery]:
        """
        Retrieves all queries linked to a specific session.
        """
        statement = select(GeneratedQuery).where(GeneratedQuery.session_id == session_id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())
